"""Core CLI logic: HTTP requests, SSE parsing, and Rich rendering."""
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
    """Yield (id, event, data) tuples from an iterable of lines."""
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
            pass # ping


def _stream_sse(run_id: str, last_id: int):
    headers = {"Last-Event-ID": str(last_id)} if last_id > 0 else {}
    
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body")
    )
    
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
                            status_text.plain = "Completed"
                            status_text.style = "bold green"
                            layout["header"].update(Panel(status_text, title="Run Status", border_style="green"))
                            live.update(layout)
                            break
                            
                        try:
                            parsed = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        # 提取 OpenAI 兼容格式里的 delta 内容
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
                            reasoning_text.append("", style="default")
                            
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
                            status_text.plain = f"Error: {parsed['error']['message']}"
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
