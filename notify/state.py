"""State management: CRUD, locking, atomic writes."""
from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable
from pathlib import Path

from notify._log import log
from notify.config import SERVE_PID_FILE, STATE_DIR


def _state_dir(project: str) -> Path:
    """Get or create the state directory for a project."""
    d = STATE_DIR / (project or "_global")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_state(project: str, filename: str) -> dict:
    """Read a JSON state file. Returns {} on any error."""
    try:
        return json.loads((_state_dir(project) / filename).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(project: str, filename: str, data: dict) -> None:
    """Write a JSON state file atomically."""
    path = _state_dir(project) / filename
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data))
        tmp.replace(path)
    except OSError as e:
        log(f"State write error: {e}")


def _clear_state(project: str, filename: str) -> None:
    """Remove a state file."""
    try:
        (_state_dir(project) / filename).unlink(missing_ok=True)
    except OSError:
        pass


def _locked_update(project: str, filename: str, updater: Callable[[dict], dict | None]) -> dict | None:
    """Atomic read-modify-write with file locking. updater(data) returns new data or None to delete."""
    path = _state_dir(project) / filename
    lock_path = path.with_suffix(".lock")
    lock_path.touch(exist_ok=True)
    fd = lock_path.open("r")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        result = updater(data)
        if result is None:
            path.unlink(missing_ok=True)
        else:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(result))
            tmp.replace(path)
        return result
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


def _is_serve_running() -> bool:
    """Check if the serve daemon is running by verifying its PID file."""
    if not SERVE_PID_FILE.exists():
        return False
    try:
        pid = int(SERVE_PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        SERVE_PID_FILE.unlink(missing_ok=True)
        return False
