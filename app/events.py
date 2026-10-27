# RunEvent / RunStatus / ModelEvent types.
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
