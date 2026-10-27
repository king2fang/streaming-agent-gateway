# SSE frame encoders. Every frame ends with a blank line.
import json
from typing import Any


def encode(event_id: int | None, event_name: str | None, data: str) -> str:
    parts = []
    if event_id is not None:
        parts.append(f"id: {event_id}")
    if event_name is not None:
        parts.append(f"event: {event_name}")
    parts.append(f"data: {data}")
    return "\n".join(parts) + "\n\n"


def encode_data(event_id: int, event_name: str | None, payload: dict[str, Any]) -> str:
    return encode(event_id, event_name, json.dumps(payload, ensure_ascii=False))


def encode_ping() -> str:
    return ": ping\n\n"


def encode_done() -> str:
    return "data: [DONE]\n\n"
