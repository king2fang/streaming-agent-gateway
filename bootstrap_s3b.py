"""S3b: agent loop + api update + tests. Run: python bootstrap_s3b.py"""
import sys
from pathlib import Path

FILES = {

"app/agent/loop.py": '''"""Agent Loop: orchestrates model streaming, tool calls, and checkpoints."""
import asyncio
import json
from typing import Any
from app.store import RunBuffer
from app.models.base import StreamingModel, ModelError
from app.agent.convert import model_event_to_run_event
from app.agent.tools import execute_tool
from app.events import ToolCallDelta
from app.config import settings


async def run_agent(buf: RunBuffer, model: StreamingModel, messages: list[dict], tools: list[dict] | None = None):
    try:
        await buf.append("run.started", {"model": model.name, "messages_count": len(messages)})
        turn = 0
        while turn < settings.max_turns:
            if buf.cancel_event.is_set():
                await buf.append("run.cancelled", {"reason": "user"})
                return
            turn += 1
            await buf.append("model.request.started", {"attempt": turn, "model": model.name})
            
            # 收集 tool_calls 用于组装
            pending_tool_calls: dict[int, dict] = {}
            finish_reason = None
            usage = None

            async for evt in model.stream(messages, tools, cancel=buf.cancel_event, request_id=buf.run_id):
                if buf.cancel_event.is_set():
                    await buf.append("run.cancelled", {"reason": "user"})
                    return
                etype, data = model_event_to_run_event(evt)
                await buf.append(etype, data)
                
                # 缓存 tool_call 以供本地执行
                if isinstance(evt, ToolCallDelta):
                    idx = evt.index
                    if idx not in pending_tool_calls:
                        pending_tool_calls[idx] = {"id": evt.id, "name": evt.name, "args": ""}
                    if evt.args_delta:
                        pending_tool_calls[idx]["args"] += evt.args_delta
                elif etype == "message.completed":
                    finish_reason = evt.finish_reason
                    usage = evt.usage

            if finish_reason == "tool_calls" and pending_tool_calls:
                # 把 assistant 的 tool_calls 消息记录到历史
                tcs = [{"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["args"]}} for tc in pending_tool_calls.values()]
                messages.append({"role": "assistant", "tool_calls": tcs})
                
                # 执行 tool 并追加结果
                for tc in pending_tool_calls.values():
                    await buf.append("tool_call.completed", {"tool_call_id": tc["id"], "name": tc["name"], "arguments": tc["args"]})
                    res, is_err = await execute_tool(tc["name"], tc["args"])
                    await buf.append("tool.result", {"tool_call_id": tc["id"], "content": res, "is_error": is_err})
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": res})
                continue # 下一轮请求模型

            # 正常结束
            break
        
        if turn >= settings.max_turns:
            await buf.append("run.failed", {"error": {"code": "max_turns_exceeded", "message": "Loop limit reached"}})
            return

        await buf.append("run.completed", {"finish_reason": finish_reason, "usage": usage})

    except ModelError as e:
        await buf.append("run.failed", {"error": {"code": e.code, "message": e.message}})
    except asyncio.CancelledError:
        await buf.append("run.cancelled", {"reason": "cancelled"})
    except Exception as e:
        await buf.append("run.failed", {"error": {"code": "internal", "message": str(e)}})
''',

"app/api/runs.py": '''"""Run endpoints: create / get / list / cancel / stream."""
import asyncio
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.store import RunRegistry
from app.models.mock import MockModel
from app.agent.loop import run_agent
from app.chunk import to_sse_frames
from app import sse
from app.config import settings

router = APIRouter(prefix="/v1")
registry = RunRegistry()
_bg: set = set()
TERMINAL = {"run.completed", "run.failed", "run.cancelled"}


def _spawn(coro) -> None:
    t = asyncio.create_task(coro)
    _bg.add(t)
    t.add_done_callback(_bg.discard)


class CreateRunRequest(BaseModel):
    model: str = "mock"
    messages: list[dict]
    tools: list[dict] | None = None
    metadata: dict | None = None


@router.post("/runs")
async def create_run(req: CreateRunRequest):
    rid = f"run-{uuid.uuid4().hex[:12]}"
    buf = registry.create(rid, req.model)
    
    # S3: 实例化模型接入 AgentLoop
    script = req.metadata.get("script", "chat") if req.metadata else "chat"
    model = MockModel(name=req.model, script=script)
    _spawn(run_agent(buf, model, req.messages, req.tools))
    
    return {"run_id": rid, "status": "pending", "stream_url": f"/v1/runs/{rid}/stream"}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    buf = registry.get(run_id)
    if not buf:
        raise HTTPException(404, {"code": "not_found", "message": "run not found"})
    return {"run_id": run_id, "status": buf.status.value, "model": buf.model,
            "created": buf.created, "seq": buf.seq}


@router.get("/runs")
async def list_runs(limit: int = 20, status: str | None = None):
    items = registry.list(limit, status)
    return {"runs": [{"run_id": b.run_id, "status": b.status.value,
                      "model": b.model, "created": b.created} for b in items]}


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    buf = registry.get(run_id)
    if not buf:
        raise HTTPException(404, {"code": "not_found", "message": "run not found"})
    if buf.done:
        return {"run_id": run_id, "status": buf.status.value}
    buf.cancel_event.set()
    return {"run_id": run_id, "status": "cancelling"}


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request):
    buf = registry.get(run_id)
    if not buf:
        raise HTTPException(404, {"code": "not_found", "message": "run not found"})
    try:
        last = int(request.headers.get("Last-Event-ID", "0"))
    except ValueError:
        last = 0
    return StreamingResponse(
        _gen(buf, last, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _gen(buf, last_seq: int, request: Request):
    earliest = buf.earliest_seq()
    if last_seq + 1 < earliest:
        gap_data = '{"earliest_available_id": %d}' % (earliest - 1)
        yield "event: gap\\ndata: " + gap_data + "\\n\\n"
        last_seq = earliest - 1
    cursor, done_sent = last_seq, False
    while True:
        if await request.is_disconnected():
            return
        pending = [e for e in list(buf.events) if e.seq > cursor]
        if pending:
            for evt in pending:
                for frame in to_sse_frames(buf.run_id, buf.model, buf.created, evt):
                    yield frame
                cursor = evt.seq
                if evt.type in TERMINAL:
                    done_sent = True
            continue
        if buf.done and cursor >= buf.seq:
            if not done_sent:
                yield sse.encode_done()
            return
        try:
            await asyncio.wait_for(buf.wait_seq_change(cursor),
                                   timeout=settings.sse_heartbeat_seconds)
        except asyncio.TimeoutError:
            yield sse.encode_ping()
''',

"tests/test_s3.py": '''"""S3: Agent Loop + MockModel + Tools."""
import asyncio
import httpx
import pytest
from httpx import ASGITransport
from app.main import app


def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _wait_terminal(client, run_id, timeout=5.0):
    start = asyncio.get_event_loop().time()
    while True:
        r = await client.get(f"/v1/runs/{run_id}")
        if r.json()["status"] in ("completed", "failed", "cancelled"):
            return r.json()["status"]
        if asyncio.get_event_loop().time() - start > timeout:
            raise AssertionError(f"timeout for {run_id}")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_chat_loop():
    async with _client() as c:
        r = await c.post("/v1/runs", json={
            "model": "mock", "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"script": "chat"}
        })
        rid = r.json()["run_id"]
        await _wait_terminal(c, rid)
        async with c.stream("GET", f"/v1/runs/{rid}/stream") as resp:
            body = (await resp.aread()).decode()
        assert "event: message.delta" in body
        assert "event: message.completed" in body
        assert "event: run.completed" in body


@pytest.mark.asyncio
async def test_tool_loop():
    async with _client() as c:
        r = await c.post("/v1/runs", json={
            "model": "mock", "messages": [{"role": "user", "content": "calc"}],
            "metadata": {"script": "tool"}
        })
        rid = r.json()["run_id"]
        await _wait_terminal(c, rid)
        async with c.stream("GET", f"/v1/runs/{rid}/stream") as resp:
            body = (await resp.aread()).decode()
        assert "event: reasoning.delta" in body
        assert "event: tool_call.started" in body
        assert "event: tool_call.arguments.delta" in body
        assert "event: tool_call.completed" in body
        assert "event: tool_result" in body
        # 由于 mock 脚本把 1+1 算出来 "2"，验证是否成功返回
        assert '\\"content\\": \\"2\\"' in body
''',

}


def main():
    root = Path.cwd()
    if not (root / "pyproject.toml").exists():
        if (root / "streaming-agent-gateway").exists():
            root = root / "streaming-agent-gateway"
        else:
            sys.exit(f"not a gateway project: {root}")
    for rel, content in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        print(f"  + {rel:28s} {content.count(chr(10)):3d} lines")
    print(f"\nDone: {len(FILES)} files")
    print("Next: rm app/fake_agent.py; pytest -v")


if __name__ == "__main__":
    main()