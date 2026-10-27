"""S4a: OpenAI compatible adapter + DeepSeek + Qwen + registry."""
import sys
from pathlib import Path

FILES = {

"app/models/openai_compat.py": r'''"""OpenAI-compatible streaming adapter (DeepSeek/Qwen)."""
import asyncio
import json
from typing import AsyncIterator
import httpx
from app.events import ReasoningDelta, ContentDelta, ToolCallDelta, Finish, ModelEvent
from app.models.base import ModelError


class OpenAICompatibleAdapter:
    def __init__(self, name: str, base_url: str, api_key: str, default_model: str):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_model = default_model

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        *,
        cancel: asyncio.Event,
        request_id: str = "",
    ) -> AsyncIterator[ModelEvent]:
        if not self.api_key:
            raise ModelError("missing_key", f"{self.name} API key is not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = {
            "model": self.default_model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        # 超时设置：连接10s，整体600s
        timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", f"{self.base_url}/chat/completions",
                    json=payload, headers=headers
                ) as response:
                    if response.status_code != 200:
                        body = await response.aread()
                        raise ModelError("api_error", f"HTTP {response.status_code}: {body[:200]}")

                    # 解析 SSE 行
                    async for line in response.aiter_lines():
                        if cancel.is_set():
                            return

                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        if not data_str:
                            continue

                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        
                        delta = choices[0].get("delta", {})
                        finish_reason = choices[0].get("finish_reason")

                        # 1. 推理内容 (DeepSeek-R1 / QwQ)
                        if "reasoning_content" in delta and delta["reasoning_content"]:
                            yield ReasoningDelta(delta["reasoning_content"])

                        # 2. 文本内容
                        if "content" in delta and delta["content"]:
                            yield ContentDelta(delta["content"])

                        # 3. Tool Calls 增量
                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", 0)
                                tc_id = tc.get("id")
                                fn = tc.get("function", {})
                                name = fn.get("name")
                                args = fn.get("arguments")
                                
                                if tc_id or name or args:
                                    yield ToolCallDelta(index=idx, id=tc_id, name=name, args_delta=args)

                        # 4. 结束
                        if finish_reason:
                            yield Finish(finish_reason=finish_reason, usage=chunk.get("usage"))
                            return

        except httpx.RequestError as e:
            raise ModelError("network_error", str(e), retryable=True)
        except asyncio.CancelledError:
            raise
''',

"app/models/deepseek.py": r'''from app.models.openai_compat import OpenAICompatibleAdapter
from app.config import settings

class DeepSeekAdapter(OpenAICompatibleAdapter):
    def __init__(self):
        super().__init__(
            name="deepseek",
            base_url=settings.deepseek_base_url,
            api_key=settings.deepseek_api_key,
            default_model=settings.deepseek_model,
        )
''',

"app/models/qwen.py": r'''from app.models.openai_compat import OpenAICompatibleAdapter
from app.config import settings

class QwenAdapter(OpenAICompatibleAdapter):
    def __init__(self):
        super().__init__(
            name="qwen",
            base_url=settings.qwen_base_url,
            api_key=settings.dashscope_api_key,
            default_model=settings.qwen_model,
        )
''',

"app/models/registry.py": r'''from app.models.base import StreamingModel
from app.models.mock import MockModel
from app.models.deepseek import DeepSeekAdapter
from app.models.qwen import QwenAdapter
from app.config import settings

class ModelRegistry:
    @staticmethod
    def get(name: str, script: str = "chat") -> StreamingModel:
        if name.startswith("deepseek"):
            return DeepSeekAdapter()
        elif name.startswith("qwen"):
            return QwenAdapter()
        else:
            return MockModel(name=name, script=script)
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
        print(f"  + {rel:32s} {content.count(chr(10)):3d} lines")
    print(f"\nDone: {len(FILES)} files")
    print("Next: run bootstrap_s4b.py")


if __name__ == "__main__":
    main()