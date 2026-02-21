"""Thread management: group session messages under one Telegram thread."""
from __future__ import annotations

import json
from typing import Any

from notify.config import STATE_DIR
from notify.session import _session_key
from notify.state import _clear_state, _read_state, _write_state


def _get_thread_id(project: str) -> int | None:
    """Get the message_id to reply to for thread grouping."""
    state = _read_state(project, "thread.json")
    session = _session_key(project)
    if state.get("session") == session:
        return state.get("message_id")
    return None


def _find_thread_by_message_id(message_id: int) -> dict | None:
    """Look up thread state across all projects by message_id."""
    if not STATE_DIR.exists():
        return None
    for project_dir in STATE_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        thread_file = project_dir / "thread.json"
        if not thread_file.exists():
            continue
        try:
            state = json.loads(thread_file.read_text())
            if state.get("message_id") == message_id:
                state["project"] = project_dir.name
                return state
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _set_thread_id(project: str, message_id: int, transcript_path: str = "") -> None:
    """Store the first message_id for thread grouping."""
    data: dict[str, Any] = {
        "session": _session_key(project),
        "message_id": message_id,
    }
    if transcript_path:
        data["transcript_path"] = transcript_path
    _write_state(project, "thread.json", data)


def _clear_thread(project: str) -> None:
    """Clear thread state."""
    _clear_state(project, "thread.json")
