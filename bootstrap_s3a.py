"""S3a: models(base, mock) + agent(tools, convert). Run: python bootstrap_s3a.py"""
import sys
from pathlib import Path

FILES = {

"app/models/__init__.py": "",

"app/models/base.py": '''"""StreamingModel interface."""
import asyncio
from typing import AsyncIterator, Protocol
from app.events import ModelEvent


class ModelError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(f"{code}: {message}")


class StreamingModel(Protocol):
    name: str

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        cancel: asyncio.Event,
        request_id: str = "",
    ) -> AsyncIterator[ModelEvent]:
        ...
''',

"app/models/mock.py": '''"""MockModel: yields preset ModelEvents with delay."""
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
''',

"app/agent/__init__.py": "",

"app/agent/tools.py": '''"""Built-in tools: echo, calculator."""
import json
import ast
import operator


async def execute_tool(name: str, args_json: str) -> tuple[str, bool]:
    """Returns (content, is_error)."""
    try:
        args = json.loads(args_json) if args_json else {}
    except json.JSONDecodeError:
        return "Invalid JSON arguments", True

    if name == "echo":
        return str(args.get("text", "")), False

    if name == "calculator":
        expr = args.get("expr", "")
        try:
            val = _safe_eval(expr)
            return str(val), False
        except Exception as e:
            return f"Calc error: {e}", True

    return f"Unknown tool: {name}", True


def _safe_eval(expr: str) -> float:
    """Minimal safe math evaluator using ast."""
    ops = {ast.Add: operator.add, ast.Sub: operator.sub,
           ast.Mult: operator.mul, ast.Div: operator.truediv}
    def _eval(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        raise ValueError("unsupported expression")
    return _eval(ast.parse(expr, mode="eval").body)
''',

"app/agent/convert.py": '''"""Convert ModelEvent to RunEvent type/data dicts."""
from app.events import ModelEvent, ReasoningDelta, ContentDelta, ToolCallDelta, Finish

def model_event_to_run_event(evt: ModelEvent) -> tuple[str, dict]:
    if isinstance(evt, ReasoningDelta):
        return "reasoning.delta", {"content": evt.content}
    if isinstance(evt, ContentDelta):
        return "message.delta", {"content": evt.content}
    if isinstance(evt, ToolCallDelta):
        if evt.id and evt.name:
            return "tool_call.started", {
                "index": evt.index, "id": evt.id, "name": evt.name
            }
        return "tool_call.arguments.delta", {
            "index": evt.index, "delta": evt.args_delta
        }
    if isinstance(evt, Finish):
        return "message.completed", {
            "finish_reason": evt.finish_reason,
            "usage": evt.usage
        }
    raise ValueError(f"Unknown ModelEvent: {evt}")
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
        print(f"  + {rel:28s} {content.count(chr(10)):3d} lines")
    print(f"\nDone: {len(FILES)} files")
    print("Next: run bootstrap_s3b.py")


if __name__ == "__main__":
    main()