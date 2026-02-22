"""Relay: inbox queue for bidirectional Telegram ↔ Claude Code messaging."""
from __future__ import annotations

import fcntl
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from hookline._log import log
from hookline.config import STATE_DIR


def _inbox_path(project: str) -> Path:
    """Get the inbox JSONL path for a project."""
    d = STATE_DIR / (project or "_global")
    d.mkdir(parents=True, exist_ok=True)
    return d / "inbox.jsonl"


def _relay_state_path(project: str) -> Path:
    """Get the relay state path for a project."""
    d = STATE_DIR / (project or "_global")
    d.mkdir(parents=True, exist_ok=True)
    return d / "relay.json"


def write_inbox(project: str, sender: str, text: str) -> str:
    """Append a message to a project's inbox. Returns the message ID."""
    msg_id = uuid.uuid4().hex[:12]
    entry = {
        "id": msg_id,
        "sender": sender,
        "text": text,
        "ts": datetime.now(timezone.utc).isoformat(),
        "read": False,
    }
    path = _inbox_path(project)
    try:
        with path.open("a") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                f.write(json.dumps(entry) + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        log(f"Inbox write error: {e}")
        raise
    return msg_id


def read_inbox(project: str, unread_only: bool = True) -> list[dict]:
    """Read messages from a project's inbox."""
    path = _inbox_path(project)
    if not path.exists():
        return []
    messages: list[dict] = []
    try:
        with path.open("r") as f:
            fcntl.flock(f, fcntl.LOCK_SH)
            try:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if unread_only and msg.get("read", False):
                            continue
                        messages.append(msg)
                    except json.JSONDecodeError:
                        continue
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        log(f"Inbox read error: {e}")
    return messages


def mark_read(project: str, message_ids: list[str] | None = None) -> int:
    """Mark inbox messages as read. If message_ids is None, marks all as read.

    Returns the count of messages marked.
    """
    path = _inbox_path(project)
    if not path.exists():
        return 0

    marked = 0
    try:
        with path.open("r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            try:
                lines = f.readlines()
                f.seek(0)
                f.truncate()
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                        if not msg.get("read", False):
                            if message_ids is None or msg.get("id") in message_ids:
                                msg["read"] = True
                                marked += 1
                        f.write(json.dumps(msg) + "\n")
                    except json.JSONDecodeError:
                        f.write(line + "\n")
            finally:
                fcntl.flock(f, fcntl.LOCK_UN)
    except OSError as e:
        log(f"Inbox mark_read error: {e}")
    return marked


def clear_inbox(project: str) -> None:
    """Remove all messages from a project's inbox."""
    path = _inbox_path(project)
    path.unlink(missing_ok=True)


def set_paused(project: str, paused: bool, by: str = "") -> None:
    """Set or clear the pause signal for a project."""
    path = _relay_state_path(project)
    if paused:
        data = {
            "paused": True,
            "paused_at": datetime.now(timezone.utc).isoformat(),
            "paused_by": by,
        }
        path.write_text(json.dumps(data))
    else:
        path.unlink(missing_ok=True)


def is_paused(project: str) -> bool:
    """Check if a project's session is paused."""
    path = _relay_state_path(project)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
        return data.get("paused", False)
    except (OSError, json.JSONDecodeError):
        return False


def list_active_sessions() -> list[dict]:
    """List all projects with active thread state (proxy for active sessions)."""
    sessions: list[dict] = []
    if not STATE_DIR.exists():
        return sessions
    for project_dir in STATE_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        if project_dir.name.startswith("_"):
            continue
        thread_file = project_dir / "thread.json"
        if not thread_file.exists():
            continue
        try:
            data = json.loads(thread_file.read_text())
            inbox_count = len(read_inbox(project_dir.name, unread_only=True))
            paused = is_paused(project_dir.name)
            sessions.append({
                "project": project_dir.name,
                "session": data.get("session", ""),
                "paused": paused,
                "unread_inbox": inbox_count,
            })
        except (OSError, json.JSONDecodeError):
            continue
    return sessions
