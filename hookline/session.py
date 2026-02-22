"""Session management: sentinel detection, age, duration, mute, enabled check."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from hookline.config import SENTINEL_DIR
from hookline.state import _clear_state, _read_state


def _sentinel_path(project: str) -> Path | None:
    """Find the active sentinel file (project-scoped or global)."""
    if project:
        p = SENTINEL_DIR / f"hookline-enabled.{project}"
        if p.exists():
            return p
    g = SENTINEL_DIR / "hookline-enabled"
    return g if g.exists() else None


def _session_key(project: str) -> str:
    """Unique key for the current session (sentinel creation timestamp)."""
    sentinel = _sentinel_path(project)
    if sentinel:
        try:
            return sentinel.read_text().strip()
        except OSError:
            pass
    return "unknown"


def _sentinel_timestamp(project: str) -> datetime | None:
    """Parse the sentinel file's ISO timestamp. Returns None if unavailable."""
    sentinel = _sentinel_path(project)
    if not sentinel:
        return None
    try:
        ts_str = sentinel.read_text().strip()
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (OSError, ValueError):
        return None


def _session_age_seconds(project: str) -> int | None:
    """Return session age in seconds, or None if unavailable."""
    started = _sentinel_timestamp(project)
    if started is None:
        return None
    return int((datetime.now(timezone.utc) - started).total_seconds())


def _session_duration(project: str) -> str | None:
    """Human-readable session duration from sentinel timestamp."""
    started = _sentinel_timestamp(project)
    if started is None:
        return None
    total_sec = int((datetime.now(timezone.utc) - started).total_seconds())
    if total_sec < 60:
        return f"{total_sec}s"
    elif total_sec < 3600:
        return f"{total_sec // 60}m"
    else:
        h, m = divmod(total_sec // 60, 60)
        return f"{h}h{m:02d}m"


def _is_muted(project: str) -> bool:
    """Check if the project is temporarily muted."""
    mute = _read_state(project, "mute.json")
    until = mute.get("until", 0)
    if until and time.time() < until:
        return True
    elif until:
        _clear_state(project, "mute.json")
    return False


def _is_enabled(project: str) -> bool:
    """Check if notifications are enabled and not muted."""
    if _sentinel_path(project) is None:
        return False
    if _is_muted(project):
        return False
    return True


def _extract_project(event: dict) -> str:
    """Extract project name from cwd."""
    cwd = event.get("cwd", "")
    return Path(cwd).name if cwd else ""
