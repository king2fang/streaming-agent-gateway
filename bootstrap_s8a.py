"""S8a: Enhance MockModel with faults + Loop robust errors."""
import sys
from pathlib import Path

FILES = {

"app/models/mock.py": r'''"""MockModel: yields preset ModelEvents with fault injection."""
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

            # 故障注入兜底：如果流结束了却没有 finish_reason（且没有 tool_calls）
            if not finish_reason and not pending_tool_calls:
                raise ModelError("stream_interrupted", "Model stream ended unexpectedly without finish_reason", retryable=True)

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

"app/models/registry.py": r'''from app.models.base import StreamingModel
from app.models.mock import MockModel
from app.models.deepseek import DeepSeekAdapter
from app.models.qwen import QwenAdapter
from app.config import settings

class ModelRegistry:
    @staticmethod
    def get(name: str, script: str = "chat", fault: str = "none") -> StreamingModel:
        if name.startswith("deepseek"):
            return DeepSeekAdapter()
        elif name.startswith("qwen"):
            return QwenAdapter()
        else:
            return MockModel(name=name, script=script, fault=fault)
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
    print("\nDone. Next: run bootstrap_s8b.py")


if __name__ == "__main__":
    main()