"""Agent Loop."""
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
