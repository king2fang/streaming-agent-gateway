"""S8b: API harness passthrough + CLI fault arg + tests."""
import sys
from pathlib import Path

FILES = {

"app/api/runs.py": r'''"""Run endpoints."""
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
''',

"app/cli/__main__.py": r'''"""CLI entrypoint."""
import argparse
import sys
from .runner import run_cmd, watch_cmd, cancel_cmd, list_cmd

def main():
    parser = argparse.ArgumentParser(description="Streaming Agent Gateway CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_run = subparsers.add_parser("run", help="Create a run and stream output")
    p_run.add_argument("--model", default="mock", help="Model name (default: mock)")
    p_run.add_argument("--prompt", required=True, help="User prompt")
    p_run.add_argument("--tools", action="store_true", help="Enable mock tools")
    p_run.add_argument("--harness", default="none", choices=["none", "error", "timeout", "drop"], help="Inject fault")
    p_run.set_defaults(func=run_cmd)

    p_watch = subparsers.add_parser("watch", help="Watch an existing run")
    p_watch.add_argument("run_id", help="The Run ID to watch")
    p_watch.add_argument("--last-id", type=int, default=0, help="Last-Event-ID to resume from")
    p_watch.set_defaults(func=watch_cmd)

    p_cancel = subparsers.add_parser("cancel", help="Cancel a running run")
    p_cancel.add_argument("run_id", help="The Run ID to cancel")
    p_cancel.set_defaults(func=cancel_cmd)

    p_list = subparsers.add_parser("list", help="List recent runs")
    p_list.set_defaults(func=list_cmd)

    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()
''',

"app/cli/runner.py": r'''"""Core CLI logic: HTTP requests, SSE parsing, and Rich rendering."""
import sys
import json
import httpx
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.layout import Layout

BASE_URL = "http://127.0.0.1:8000"
console = Console()

def _parse_sse(lines):
    eid, event, data = None, "message", []
    for line in lines:
        if not line:
            if data:
                yield eid, event, "".join(data)
            eid, event, data = None, "message", []
            continue
        
        if line.startswith("id: "):
            eid = int(line[4:])
        elif line.startswith("event: "):
            event = line[7:]
        elif line.startswith("data: "):
            data.append(line[6:])
        elif line.startswith(": "):
            pass


def _stream_sse(run_id: str, last_id: int):
    headers = {"Last-Event-ID": str(last_id)} if last_id > 0 else {}
    layout = Layout()
    layout.split_column(Layout(name="header", size=3), Layout(name="body"))
    
    status_text = Text("Initializing...", style="bold yellow")
    output_text = Text()
    reasoning_text = Text()
    layout["header"].update(Panel(status_text, title="Run Status", border_style="blue"))
    
    try:
        with httpx.Client(timeout=None) as client:
            with client.stream("GET", f"{BASE_URL}/v1/runs/{run_id}/stream", headers=headers) as resp:
                if resp.status_code != 200:
                    console.print(f"[red]Error: HTTP {resp.status_code}[/red]")
                    return

                with Live(layout, refresh_per_second=10, console=console) as live:
                    def update_body():
                        layout["body"].update(Panel(Text.assemble(reasoning_text, output_text), title="Output"))

                    for eid, event, data in _parse_sse(resp.iter_lines()):
                        if data == "[DONE]":
                            live.update(layout)
                            break
                            
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        delta = {}
                        if "choices" in parsed and len(parsed["choices"]) > 0:
                            delta = parsed["choices"][0].get("delta", {})

                        if event == "run.started":
                            status_text.plain = f"Running (Model: {parsed.get('model')})"
                            status_text.style = "bold cyan"
                            layout["header"].update(Panel(status_text, title="Run Status", border_style="cyan"))
                        
                        elif event == "model.request.started":
                            status_text.plain = f"Model thinking (Turn {parsed.get('attempt')})..."
                            status_text.style = "bold yellow"
                            layout["header"].update(Panel(status_text, title="Run Status", border_style="yellow"))
                            
                        elif event == "reasoning.delta":
                            if "reasoning_content" in delta:
                                reasoning_text.append(delta["reasoning_content"], style="dim italic")
                                update_body()
                            
                        elif event == "message.delta":
                            if "content" in delta:
                                output_text.append(delta["content"], style="bold white")
                                update_body()
                            
                        elif event == "run.completed":
                            tokens = parsed.get("usage", {}).get("total_tokens", 0)
                            status_text.plain = f"Completed (Tokens: {tokens})"
                            status_text.style = "bold green"
                            layout["header"].update(Panel(status_text, title="Run Status", border_style="green"))
                            live.update(layout)
                            
                        elif event == "error":
                            err = parsed.get("error", {})
                            status_text.plain = f"Error: {err.get('code')} - {err.get('message')}"
                            status_text.style = "bold red"
                            layout["header"].update(Panel(status_text, title="Run Status", border_style="red"))
                            live.update(layout)
                            console.print("\n[red]Run failed.[/red]")
                            sys.exit(1)
                            
    except KeyboardInterrupt:
        console.print(f"\n[yellow]Disconnected. Run is still active on server.[/yellow]")
        console.print(f"To resume watching, run: [bold]sag watch {run_id} --last-id <N>[/bold]")
        sys.exit(0)
    except httpx.RequestError as e:
        console.print(f"\n[red]Network error: {e}[/red]")
        sys.exit(1)


def run_cmd(args):
    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": args.prompt}],
        "metadata": {"fault": args.harness}
    }
    if args.tools:
        payload["tools"] = [{"type": "function", "function": {"name": "calculator"}}]

    try:
        with httpx.Client() as client:
            resp = client.post(f"{BASE_URL}/v1/runs", json=payload)
            resp.raise_for_status()
            run_id = resp.json()["run_id"]
            console.print(f"Created run: [bold cyan]{run_id}[/bold cyan]")
            _stream_sse(run_id, 0)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]API Error: {e.response.text}[/red]")
        sys.exit(1)


def watch_cmd(args):
    console.print(f"Watching run: [bold cyan]{args.run_id}[/bold cyan] (from ID {args.last_id})")
    _stream_sse(args.run_id, args.last_id)


def cancel_cmd(args):
    with httpx.Client() as client:
        resp = client.post(f"{BASE_URL}/v1/runs/{args.run_id}/cancel")
        if resp.status_code == 200:
            console.print(f"[yellow]Cancelled: {args.run_id}[/yellow]")
        else:
            console.print(f"[red]Error: {resp.text}[/red]")


def list_cmd(args):
    with httpx.Client() as client:
        resp = client.get(f"{BASE_URL}/v1/runs")
        if resp.status_code == 200:
            from rich.table import Table
            table = Table(title="Recent Runs")
            table.add_column("Run ID", style="cyan")
            table.add_column("Model", style="magenta")
            table.add_column("Status", style="bold")
            
            for r in resp.json()["runs"]:
                color = "green" if r["status"] == "completed" else "red" if r["status"] == "failed" else "yellow"
                table.add_row(r["run_id"], r["model"], f"[{color}]{r['status']}[/{color}]")
            console.print(table)
''',

"tests/test_s8.py": r'''"""S8: Harness fault injection tests."""
import asyncio
import httpx
import pytest
from httpx import ASGITransport
from app.main import app

def _client():
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

async def _wait_terminal(client, run_id, timeout=3.0):
    start = asyncio.get_event_loop().time()
    while True:
        r = await client.get(f"/v1/runs/{run_id}")
        status = r.json()["status"]
        if status in ("completed", "failed", "cancelled"):
            return status
        if asyncio.get_event_loop().time() - start > timeout:
            raise AssertionError(f"timeout for {run_id}, status: {status}")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_fault_error():
    """Test API error injection."""
    async with _client() as c:
        r = await c.post("/v1/runs", json={
            "model": "mock", "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"fault": "error"}
        })
        rid = r.json()["run_id"]
        status = await _wait_terminal(c, rid)
        assert status == "failed"
        
        async with c.stream("GET", f"/v1/runs/{rid}/stream") as resp:
            body = (await resp.aread()).decode()
        assert "event: error" in body
        assert "mock_api_error" in body


@pytest.mark.asyncio
async def test_fault_drop():
    """Test unexpected stream end."""
    async with _client() as c:
        r = await c.post("/v1/runs", json={
            "model": "mock", "messages": [{"role": "user", "content": "hi"}],
            "metadata": {"fault": "drop"}
        })
        rid = r.json()["run_id"]
        status = await _wait_terminal(c, rid)
        assert status == "failed"
        
        async with c.stream("GET", f"/v1/runs/{rid}/stream") as resp:
            body = (await resp.aread()).decode()
        assert "stream_interrupted" in body
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
        print(f"  = {rel:28s} {content.count(chr(10)):3d} lines")
    print(f"\nDone: {len(FILES)} files")
    print("Next: pytest -v")


if __name__ == "__main__":
    main()