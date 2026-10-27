import json
from app.events import RunEvent, RunStatus, ContentDelta, ToolCallDelta, Finish
from app.sse import encode_data, encode_ping, encode_done
from app.chunk import to_sse_frames


def _data(frame):
    for line in frame.split("\n"):
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
    assert encode_data(1, None, {"a": 1}) == 'id: 1\ndata: {"a": 1}\n\n'

def test_encode_with_event():
    assert encode_data(2, "msg", {"x": 1}) == 'id: 2\nevent: msg\ndata: {"x": 1}\n\n'

def test_ping_done():
    assert encode_ping() == ": ping\n\n"
    assert encode_done() == "data: [DONE]\n\n"


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
    assert frames[1] == "data: [DONE]\n\n"

def test_run_failed_emits_error_and_done():
    e = RunEvent("r1", 3, 100, "run.failed", {"error": {"code": "x", "message": "y"}})
    frames = to_sse_frames("r1", "m", 100, e)
    assert len(frames) == 2
    assert "event: error" in frames[0]
    assert frames[1] == "data: [DONE]\n\n"

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
