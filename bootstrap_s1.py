"""S1 bootstrap: events + sse + chunk (3 src + 1 test). Run: python bootstrap_s1.py"""
import sys
from pathlib import Path

FILES = {

"app/events.py": """# RunEvent / RunStatus / ModelEvent types.
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Union


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass
class RunEvent:
    run_id: str
    seq: int
    ts: int
    type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningDelta:
    content: str


@dataclass
class ContentDelta:
    content: str


@dataclass
class ToolCallDelta:
    index: int
    id: str | None = None
    name: str | None = None
    args_delta: str | None = None


@dataclass
class Finish:
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None


ModelEvent = Union[ReasoningDelta, ContentDelta, ToolCallDelta, Finish]
""",

"app/sse.py": """# SSE frame encoders. Every frame ends with a blank line.
import json
from typing import Any


def encode(event_id: int | None, event_name: str | None, data: str) -> str:
    parts = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    if event_name is not None:
        parts.append(f"event: {event_name}")
    parts.append(f"data: {data}")
    return "\\n".join(parts) + "\\n\\n"


def encode_data(event_id: int, event_name: str | None, payload: dict[str, Any]) -> str:
    return encode(event_id, event_name, json.dumps(payload, ensure_ascii=False))


def encode_ping() -> str:
    return ": ping\\n\\n"


def encode_done() -> str:
    return "data: [DONE]\\n\\n"
""",

"app/chunk.py": """# RunEvent -> SSE frames. Standard chunk for content/tool; named events for status.
from typing import Any
from app.events import RunEvent
from app import sse


def _base(run_id, model, created):
    return {"id": f"chatcmpl-{run_id}", "object": "chat.completion.chunk",
            "created": created, "model": model}


def _choice(delta, finish_reason=None):
    return [{"index": 0, "delta": delta, "finish_reason": finish_reason}]


def to_sse_frames(run_id: str, model: str, created: int, event: RunEvent) -> list[str]:
    base = _base(run_id, model, created)
    t, d, eid = event.type, event.data, event.seq

    if t == "message.delta":
        return [sse.encode_data(eid, t, {**base, "choices": _choice({"content": d["content"]})})]

    if t == "reasoning.delta":
        return [sse.encode_data(eid, t, {**base, "choices": _choice({"reasoning_content": d["content"]})})]

    if t == "tool_call.started":
        tc = {"index": d.get("index", 0), "id": d.get("id", ""), "type": "function",
              "function": {"name": d.get("name", ""), "arguments": ""}}
        return [sse.encode_data(eid, t, {**base, "choices": _choice({"tool_calls": [tc]})})]

    if t == "tool_call.arguments.delta":
        tc = {"index": d.get("index", 0), "function": {"arguments": d.get("delta", "")}}
        return [sse.encode_data(eid, t, {**base, "choices": _choice({"tool_calls": [tc]})})]

    if t == "message.completed":
        payload = {**base, "choices": _choice({}, d.get("finish_reason")), "usage": d.get("usage")}
        return [sse.encode_data(eid, t, payload)]

    if t == "run.completed":
        payload = {**base, "choices": _choice({}, d.get("finish_reason", "stop")), "usage": d.get("usage")}
        return [sse.encode_data(eid, t, payload), sse.encode_done()]

    if t == "run.failed":
        return [sse.encode_data(eid, "error", {"id": base["id"], "error": d["error"]}),
                sse.encode_done()]

    if t == "run.cancelled":
        return [sse.encode_data(eid, "cancelled",
                                {"id": base["id"], "reason": d.get("reason", "cancelled")}),
                sse.encode_done()]

    if t == "tool_call.completed":
        payload = {"tool_call_id": d.get("tool_call_id"), "name": d.get("name"),
                   "arguments": d.get("arguments")}
        return [sse.encode_data(eid, "tool_call.completed", payload)]

    if t == "tool.result":
        payload = {"tool_call_id": d.get("tool_call_id"), "content": d.get("content"),
                   "is_error": d.get("is_error", False)}
        return [sse.encode_data(eid, "tool_result", payload)]

    if t == "run.started":
        return [sse.encode_data(eid, "run.started",
                                {"model": d.get("model"), "messages_count": d.get("messages_count")})]

    if t == "model.request.started":
        return [sse.encode_data(eid, "model.request.started",
                                {"attempt": d.get("attempt", 1), "model": d.get("model")})]

    return [sse.encode_data(eid, t, d)]
""",

"tests/test_s1.py": """import json
from app.events import RunEvent, RunStatus, ContentDelta, ToolCallDelta, Finish
from app.sse import encode_data, encode_ping, encode_done
from app.chunk import to_sse_frames


def _data(frame):
    for line in frame.split("\\n"):
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AssertionError("no data line")


# --- events ---
def test_run_event_defaults():
    assert RunEvent("r", 1, 0, "x").data == {}

def test_run_status():
    assert RunStatus.CANCELLED.value == "cancelled"
    assert RunStatus.INTERRUPTED.value == "interrupted"

def test_model_events():
    assert ContentDelta("hi").content == "hi"
    assert ToolCallDelta(index=0, name="calc").name == "calc"
    assert Finish(finish_reason="stop", usage={"t": 1}).usage == {"t": 1}


# --- sse ---
def test_encode_no_event():
    assert encode_data(1, None, {"a": 1}) == 'id: 1\\ndata: {"a": 1}\\n\\n'

def test_encode_with_event():
    assert encode_data(2, "msg", {"x": 1}) == 'id: 2\\nevent: msg\\ndata: {"x": 1}\\n\\n'

def test_ping_done():
    assert encode_ping() == ": ping\\n\\n"
    assert encode_done() == "data: [DONE]\\n\\n"


# --- chunk ---
def test_message_delta():
    e = RunEvent("r1", 1, 100, "message.delta", {"content": "hi"})
    d = _data(to_sse_frames("r1", "m", 100, e)[0])
    assert d["id"] == "chatcmpl-r1"
    assert d["object"] == "chat.completion.chunk"
    assert d["choices"][0]["delta"]["content"] == "hi"
    assert d["choices"][0]["finish_reason"] is None

def test_reasoning_delta():
    e = RunEvent("r1", 2, 100, "reasoning.delta", {"content": "think"})
    d = _data(to_sse_frames("r1", "m", 100, e)[0])
    assert d["choices"][0]["delta"]["reasoning_content"] == "think"

def test_run_completed_emits_done():
    e = RunEvent("r1", 5, 100, "run.completed", {"finish_reason": "stop", "usage": {"t": 10}})
    frames = to_sse_frames("r1", "m", 100, e)
    assert len(frames) == 2
    assert frames[1] == "data: [DONE]\\n\\n"

def test_run_failed_emits_error_and_done():
    e = RunEvent("r1", 3, 100, "run.failed", {"error": {"code": "x", "message": "y"}})
    frames = to_sse_frames("r1", "m", 100, e)
    assert len(frames) == 2
    assert "event: error" in frames[0]
    assert frames[1] == "data: [DONE]\\n\\n"

def test_run_cancelled():
    e = RunEvent("r1", 4, 100, "run.cancelled", {"reason": "user"})
    frames = to_sse_frames("r1", "m", 100, e)
    assert "event: cancelled" in frames[0]

def test_tool_call_started():
    e = RunEvent("r1", 1, 100, "tool_call.started", {"index": 0, "id": "c1", "name": "calc"})
    d = _data(to_sse_frames("r1", "m", 100, e)[0])
    tc = d["choices"][0]["delta"]["tool_calls"][0]
    assert tc["id"] == "c1"
    assert tc["function"]["name"] == "calc"
    assert tc["function"]["arguments"] == ""

def test_unknown_event_passthrough():
    e = RunEvent("r1", 9, 100, "custom.event", {"k": "v"})
    frames = to_sse_frames("r1", "m", 100, e)
    assert "event: custom.event" in frames[0]
""",

}


def main():
    root = Path.cwd()
    if not (root / "pyproject.toml").exists():
        if (root / "streaming-agent-gateway").exists():
            root = root / "streaming-agent-gateway"
        else:
            sys.exit(f"not a gateway project: {root} (no pyproject.toml)")

    for rel, content in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        print(f"  + {rel:28s} {content.count(chr(10)):3d} lines")

    print(f"\nDone: {len(FILES)} files -> {root}")
    print("Next: pytest -v")


if __name__ == "__main__":
    main()