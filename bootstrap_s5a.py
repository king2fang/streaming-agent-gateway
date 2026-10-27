"""S5a: Adapter timeouts & cancellation."""
import sys
from pathlib import Path

FILES = {

"app/models/openai_compat.py": r'''"""OpenAI-compatible streaming adapter."""
import asyncio
import json
from typing import AsyncIterator
import httpx
from app.events import ReasoningDelta, ContentDelta, ToolCallDelta, Finish, ModelEvent
from app.models.base import ModelError


class OpenAICompatibleAdapter:
    def __init__(self, name: str, base_url: str, api_key: str, default_model: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        cancel: asyncio.Event | None = None,
        request_id: str = "",
    ) -> AsyncIterator[ModelEvent]:
        if not self.api_key:
            raise ModelError("missing_key", f"{self.name} API key is not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "model": self.default_model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        # 超时设置：连接10s，总长300s
        timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions",
                    json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise ModelError("api_error", f"HTTP {response.status_code}: {body[:200]}")

                    async for line in response.aiter_lines():
                        if cancel and cancel.is_set():
                            raise asyncio.CancelledError()

                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        if not data_str:
                            continue

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        
                        delta = choices[0].get("delta", {})
                        finish_reason = choices[0].get("finish_reason")

                        if "reasoning_content" in delta and delta["reasoning_content"]:
                            yield ReasoningDelta(delta["reasoning_content"])

                        if "content" in delta and delta["content"]:
                            yield ContentDelta(delta["content"])

                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                tc_id = tc.get("id")
                                fn = tc.get("function", {})
                                name = fn.get("name")
                                args = fn.get("arguments")
                                if tc_id or name or args:
                                    yield ToolCallDelta(index=idx, id=tc_id, name=name, args_delta=args)

                        if finish_reason:
                            yield Finish(finish_reason=finish_reason, usage=chunk.get("usage"))
                            return

        except httpx.TimeoutException as e:
            raise ModelError("timeout", f"Model request timed out: {str(e)}", retryable=True)
        except httpx.RequestError as e:
            raise ModelError("network_error", str(e), retryable=True)
        except asyncio.CancelledError:
            raise
''',

"app/agent/loop.py": r'''"""Agent Loop."""
import asyncio
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
                raise asyncio.CancelledError()
            
            turn += 1
            await buf.append("model.request.started", {"attempt": turn, "model": model.name})
            
            pending_tool_calls: dict[int, dict] = {}
            finish_reason = None
            usage = None

            async for evt in model.stream(messages, tools, cancel=buf.cancel_event, request_id=buf.run_id):
                if buf.cancel_event.is_set():
                    raise asyncio.CancelledError()
                
                etype, data = model_event_to_run_event(evt)
                await buf.append(etype, data)
                
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
                tcs = [{"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["args"]}} for tc in pending_tool_calls.values()]
                messages.append({"role": "assistant", "tool_calls": tcs})
                
                for tc in pending_tool_calls.values():
                    await buf.append("tool_call.completed", {"tool_call_id": tc["id"], "name": tc["name"], "arguments": tc["args"]})
                    res, is_err = await execute_tool(tc["name"], tc["args"])
                    await buf.append("tool.result", {"tool_call_id": tc["id"], "content": res, "is_error": is_err})
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": res})
                continue

            break
        
        if turn >= settings.max_turns:
            raise ModelError("max_turns_exceeded", "Loop limit reached")

        await buf.append("run.completed", {"finish_reason": finish_reason, "usage": usage})

    except asyncio.CancelledError:
        await buf.append("run.cancelled", {"reason": "user"})
    except ModelError as e:
        await buf.append("run.failed", {"error": {"code": e.code, "message": e.message}})
    except Exception as e:
        await buf.append("run.failed", {"error": {"code": "internal", "message": str(e)}})
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
        p.write_text(content, encoding="utf-8", newline="\n")
        print(f"  = {rel:28s} {content.count(chr(10)):3d} lines")
    print("\nDone. Next: run bootstrap_s5b.py")


if __name__ == "__main__":
    main()