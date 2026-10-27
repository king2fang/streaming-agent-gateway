# RunEvent -> SSE frames. Standard chunk for content/tool; named events for status.
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
