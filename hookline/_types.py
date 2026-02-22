"""Type definitions for hookline state structures."""
from __future__ import annotations

from typing import Any, TypedDict


class ThreadState(TypedDict, total=False):
    session: str
    message_id: int
    transcript_path: str
    project: str


class MuteState(TypedDict, total=False):
    until: float


class TaskState(TypedDict, total=False):
    session: str
    completed: list[str]
    total: int | None


class DebounceEventInfo(TypedDict):
    count: int
    names: list[str]


class DebounceState(TypedDict, total=False):
    events: dict[str, DebounceEventInfo]
    first_time: float
    first_utc: str
    last_time: float
    last_utc: str


class ApprovalState(TypedDict, total=False):
    approval_id: str
    message_id: int
    project: str
    tool_name: str
    tool_input: dict[str, Any]
    pipe_path: str
    created_at: str
    event: dict[str, Any]
    decided_by: str
    decision: str
    reason: str


class LastButtonState(TypedDict):
    session: str
    message_id: int
