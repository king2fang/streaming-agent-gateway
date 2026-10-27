"""MockModel: yields preset ModelEvents with fault injection."""
import asyncio
from typing import AsyncIterator
from app.events import ReasoningDelta, ContentDelta, ToolCallDelta, Finish, ModelEvent
from app.models.base import ModelError


class MockModel:
    def __init__(self, name: str = "mock", delay: float = 0.05, script: str = "chat", fault: str = "none"):
        self.name = name
        self.delay = delay
        self.script = script
        self.fault = fault

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        cancel: asyncio.Event | None = None,
        request_id: str = "",
    ) -> AsyncIterator[ModelEvent]:
        if self.script == "tool":
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
        for i, w in enumerate(words):
            if cancel and cancel.is_set():
                return
            
            # 故障注入 1：中途报错
            if self.fault == "error" and i == 2:
                raise ModelError("mock_api_error", "Simulated 500 Internal Server Error", retryable=True)
            
            # 故障注入 2：卡死超时 (模拟网络黑洞)
            if self.fault == "timeout" and i == 1:
                await asyncio.sleep(999)
                return

            # 故障注入 3：断流 (不发 Finish 直接结束)
            if self.fault == "drop" and i == 3:
                return

            await asyncio.sleep(self.delay)
            yield ContentDelta(w)
            
        yield Finish(finish_reason="stop", usage={"total_tokens": 12})
