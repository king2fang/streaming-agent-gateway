"""Agent Loop: orchestrates model streaming, tool calls, and checkpoints."""
import asyncio
import json
from typing import Any
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
                await buf.append("run.cancelled", {"reason": "user"})
                return
            turn += 1
            await buf.append("model.request.started", {"attempt": turn, "model": model.name})
            
            # 收集 tool_calls 用于组装
            pending_tool_calls: dict[int, dict] = {}
            finish_reason = None
            usage = None

            async for evt in model.stream(messages, tools, cancel=buf.cancel_event, request_id=buf.run_id):
                if buf.cancel_event.is_set():
                    await buf.append("run.cancelled", {"reason": "user"})
                    return
                etype, data = model_event_to_run_event(evt)
                await buf.append(etype, data)
                
                # 缓存 tool_call 以供本地执行
                if isinstance(evt, ToolCallDelta):
                    idx = evt.index
                    if idx not in pending_tool_calls:
                        pending_tool_calls[idx] = {"id": evt.id, "name": evt.name, "args": ""}
                    if evt.args_delta:
                        pending_tool_calls[idx]["args"] += evt.args_delta
                elif etype == "message.completed":
                    finish_reason = evt.finish_reason
                    usage = evt.usage

            if finish_reason == "tool_calls" and pending_tool_calls:
                # 把 assistant 的 tool_calls 消息记录到历史
                tcs = [{"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["args"]}} for tc in pending_tool_calls.values()]
                messages.append({"role": "assistant", "tool_calls": tcs})
                
                # 执行 tool 并追加结果
                for tc in pending_tool_calls.values():
                    await buf.append("tool_call.completed", {"tool_call_id": tc["id"], "name": tc["name"], "arguments": tc["args"]})
                    res, is_err = await execute_tool(tc["name"], tc["args"])
                    await buf.append("tool.result", {"tool_call_id": tc["id"], "content": res, "is_error": is_err})
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": res})
                continue # 下一轮请求模型

            # 正常结束
            break
        
        if turn >= settings.max_turns:
            await buf.append("run.failed", {"error": {"code": "max_turns_exceeded", "message": "Loop limit reached"}})
            return

        await buf.append("run.completed", {"finish_reason": finish_reason, "usage": usage})

    except ModelError as e:
        await buf.append("run.failed", {"error": {"code": e.code, "message": e.message}})
    except asyncio.CancelledError:
        await buf.append("run.cancelled", {"reason": "cancelled"})
    except Exception as e:
        await buf.append("run.failed", {"error": {"code": "internal", "message": str(e)}})
