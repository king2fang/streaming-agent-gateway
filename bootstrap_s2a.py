"""S2a: config update + store + fake_agent. Run: python bootstrap_s2a.py"""
import sys
from pathlib import Path

FILES = {

"app/config.py": """from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    host: str = "127.0.0.1"
    port: int = 8000
    max_events_per_run: int = 2000
    run_retention_seconds: int = 86400
    sse_heartbeat_seconds: int = 15
    max_turns: int = 8

settings = Settings()
""",

"app/store.py": '''"""RunBuffer, RunRegistry."""
import asyncio
import time
from collections import deque
from app.events import RunEvent, RunStatus
from app.config import settings


class RunBuffer:
    def __init__(self, run_id: str, model: str, created: int):
        self.run_id = run_id
        self.model = model
        self.created = created
        self.events: deque[RunEvent] = deque(maxlen=settings.max_events_per_run)
        self.seq = 0
        self.done = False
        self.status = RunStatus.PENDING
        self.cancel_event = asyncio.Event()
        self.cond = asyncio.Condition()
        self.last_touch = time.time()

    def earliest_seq(self) -> int:
        return self.events[0].seq if self.events else self.seq + 1

    async def append(self, etype: str, data: dict) -> RunEvent:
        async with self.cond:
            self.seq += 1
            evt = RunEvent(self.run_id, self.seq, int(time.time() * 1000), etype, data)
            self.events.append(evt)
            self.last_touch = time.time()
            if etype == "run.started":
                self.status = RunStatus.RUNNING
            elif etype == "run.completed":
                self.status, self.done = RunStatus.COMPLETED, True
            elif etype == "run.failed":
                self.status, self.done = RunStatus.FAILED, True
            elif etype == "run.cancelled":
                self.status, self.done = RunStatus.CANCELLED, True
            self.cond.notify_all()
            return evt

    async def wait_seq_change(self, cursor: int) -> None:
        async with self.cond:
            await self.cond.wait_for(lambda: self.seq > cursor or self.done)


class RunRegistry:
    def __init__(self) -> None:
        self.runs: dict[str, RunBuffer] = {}

    def create(self, run_id: str, model: str) -> RunBuffer:
        buf = RunBuffer(run_id, model, int(time.time()))
        self.runs[run_id] = buf
        return buf

    def get(self, run_id: str) -> RunBuffer | None:
        return self.runs.get(run_id)

    def list(self, limit: int, status_filter: str | None) -> list[RunBuffer]:
        items = list(self.runs.values())
        if status_filter:
            items = [b for b in items if b.status.value == status_filter]
        items.sort(key=lambda b: b.created, reverse=True)
        return items[:limit]

    async def cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(60)
            now = time.time()
            for rid, buf in list(self.runs.items()):
                if buf.done and now - buf.last_touch > settings.run_retention_seconds:
                    self.runs.pop(rid, None)
''',

"app/fake_agent.py": '''"""FakeAgent: emit preset events with delay."""
import asyncio


class FakeAgent:
    def __init__(self, buf, messages, delay: float = 0.2):
        self.buf = buf
        self.messages = messages
        self.delay = delay

    async def run(self) -> None:
        try:
            await self.buf.append("run.started",
                                  {"model": self.buf.model, "messages_count": len(self.messages)})
            await asyncio.sleep(self.delay * 0.5)
            for tok in ["Hello", ", ", "world", "!"]:
                if self.buf.cancel_event.is_set():
                    await self.buf.append("run.cancelled", {"reason": "user"})
                    return
                await asyncio.sleep(self.delay)
                await self.buf.append("message.delta", {"content": tok})
            if self.buf.cancel_event.is_set():
                await self.buf.append("run.cancelled", {"reason": "user"})
                return
            await self.buf.append("message.completed",
                                  {"content": "Hello, world!", "finish_reason": "stop",
                                   "usage": {"total_tokens": 5}})
            await self.buf.append("run.completed",
                                  {"finish_reason": "stop", "usage": {"total_tokens": 5}})
        except Exception as e:
            await self.buf.append("run.failed",
                                  {"error": {"code": "internal", "message": str(e)}})
''',

"app/api/__init__.py": "",

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
    print("Next: run bootstrap_s2b.py")


if __name__ == "__main__":
    main()