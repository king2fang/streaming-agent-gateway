"""RunBuffer, RunRegistry."""
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
