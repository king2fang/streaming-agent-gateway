"""MockModel: yields preset ModelEvents with delay."""
import asyncio
from typing import AsyncIterator
from app.events import ReasoningDelta, ContentDelta, ToolCallDelta, Finish, ModelEvent


class MockModel:
    def __init__(self, name: str = "mock", delay: float = 0.05, script: str = "chat"):
        self.name = name
        self.delay = delay
        self.script = script

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        cancel: asyncio.Event,
        request_id: str = "",
    ) -> AsyncIterator[ModelEvent]:
        if self.script == "tool":
            # 故意触发一次 tool_call，检验 loop 的拼接与执行
            yield ReasoningDelta("Let me calculate. ")
            await asyncio.sleep(self.delay)
            yield ContentDelta("Thinking... ")
            await asyncio.sleep(self.delay)
            
            yield ToolCallDelta(index=0, id="call_1", name="calculator", args_delta='{"expr":')
            await asyncio.sleep(self.delay)
            yield ToolCallDelta(index=0, args_delta=' "1+1"}')
            await asyncio.sleep(self.delay)
            yield Finish(finish_reason="tool_calls")
            return

        # 默认纯聊天脚本
        words = ["Hello", ", ", "I ", "am ", "a ", "Mock", " Model", "!"]
        for w in words:
            if cancel.is_set():
                return
            await asyncio.sleep(self.delay)
            yield ContentDelta(w)
        yield Finish(finish_reason="stop", usage={"total_tokens": 12})
