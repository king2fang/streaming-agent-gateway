"""Run endpoints."""
import asyncio
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from app.store import RunRegistry
from app.models.registry import ModelRegistry
from app.agent.loop import run_agent
from app.chunk import to_sse_frames
from app import sse
from app.config import settings

router = APIRouter(prefix="/v1")
registry = RunRegistry()
_bg_tasks: dict[str, asyncio.Task] = {}
TERMINAL = {"run.completed", "run.failed", "run.cancelled"}

class CreateRunRequest(BaseModel):
    model: str = "mock"
    messages: list[dict]
    tools: list[dict] | None = None
    metadata: dict | None = None

@router.post("/runs")
async def create_run(req: CreateRunRequest):
    rid = f"run-{uuid.uuid4().hex[:12]}"
    buf = registry.create(rid, req.model)
    
    script = req.metadata.get("script", "chat") if req.metadata else "chat"
    fault = req.metadata.get("fault", "none") if req.metadata else "none"
    
    try:
        model = ModelRegistry.get(req.model, script, fault)
    except Exception as e:
        raise HTTPException(400, {"code": "bad_model", "message": str(e)})

    task = asyncio.create_task(run_agent(buf, model, req.messages, req.tools))
    _bg_tasks[rid] = task
    task.add_done_callback(lambda t: _bg_tasks.pop(rid, None))

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
    task = _bg_tasks.get(run_id)
    if task and not task.done():
        task.cancel()
        
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
        yield "event: gap\ndata: " + gap_data + "\n\n"
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
