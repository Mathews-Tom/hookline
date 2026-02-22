"""Task tracking: completed tasks per session for progress display."""
from __future__ import annotations

from hookline.session import _session_key
from hookline.state import _clear_state, _read_state, _write_state


def _track_task(project: str, event: dict) -> tuple[int, int | None]:
    """Record a completed task. Returns (completed_count, total_or_None)."""
    state = _read_state(project, "tasks.json")
    session = _session_key(project)

    if state.get("session") != session:
        state = {"session": session, "completed": [], "total": None}

    task_id = str(event.get("task_id", ""))
    completed = state.get("completed", [])
    if task_id and task_id not in completed:
        completed.append(task_id)
    state["completed"] = completed

    total = state.get("total")
    try:
        num = int(task_id)
        if total is None or num > total:
            state["total"] = num
            total = num
    except (ValueError, TypeError):
        pass

    _write_state(project, "tasks.json", state)
    return len(completed), total


def _clear_tasks(project: str) -> None:
    """Clear task state."""
    _clear_state(project, "tasks.json")
