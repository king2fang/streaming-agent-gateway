"""FakeAgent: emit preset events with delay."""
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
