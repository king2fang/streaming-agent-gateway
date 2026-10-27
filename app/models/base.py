"""StreamingModel interface."""
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
