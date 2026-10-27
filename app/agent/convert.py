"""Convert ModelEvent to RunEvent type/data dicts."""
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
