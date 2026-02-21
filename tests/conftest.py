"""Shared fixtures for claude-notify tests."""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from types import ModuleType

import pytest


@pytest.fixture()
def _add_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Add the project root to sys.path so we can import notify."""
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        monkeypatch.syspath_prepend(root)


@pytest.fixture()
def notify(_add_project_root: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:  # noqa: ARG001
    """Import notify package with sandboxed state directory and no real Telegram calls."""
    import notify as _notify

    # __init__.py re-exports shadow submodule names (e.g., notify.serve = function).
    # Use sys.modules to get the actual module objects.
    def _submod(name: str) -> ModuleType:
        importlib.import_module(f"notify.{name}")
        return sys.modules[f"notify.{name}"]

    _config = _submod("config")
    _state = _submod("state")
    _session = _submod("session")
    _project = _submod("project")
    _transcript = _submod("transcript")
    _telegram = _submod("telegram")
    _approval = _submod("approval")
    _serve = _submod("serve")
    _debounce = _submod("debounce")

    state_dir = tmp_path / "notify-state"
    state_dir.mkdir()
    pid_file = state_dir / "serve.pid"

    # All submodules that need patching
    _main = _submod("__main__")
    _threads = _submod("threads")
    _replies = _submod("replies")
    all_mods = [
        _config, _state, _session, _project, _transcript, _telegram,
        _approval, _serve, _debounce, _main, _threads, _replies,
    ]

    # Patch each attribute only in modules that actually have it
    patches: dict[str, object] = {
        "STATE_DIR": state_dir,
        "SERVE_PID_FILE": pid_file,
        "SENTINEL_DIR": tmp_path,
        "AUDIT_LOG": state_dir / "audit.jsonl",
        "DRY_RUN": False,
        "BOT_TOKEN": "test-token",
        "CHAT_ID": "12345",
    }
    for attr, value in patches.items():
        for mod in all_mods:
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, value)

    # Clear caches
    monkeypatch.setattr(_config, "_notify_config", None)
    monkeypatch.setattr(_project, "_project_config", None)
    monkeypatch.setattr(_transcript, "_transcript_cache", {})

    # Patch the re-exports on the package itself for direct access
    for attr, value in patches.items():
        if hasattr(_notify, attr):
            monkeypatch.setattr(_notify, attr, value)

    return _notify


@pytest.fixture()
def mock_telegram(notify: Any, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Replace _telegram_api with a call recorder."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_api(method: str, payload: dict[str, Any], timeout: int = 10) -> dict[str, Any] | None:  # noqa: ARG001
        calls.append((method, payload))
        if method == "sendMessage":
            return {"ok": True, "result": {"message_id": len(calls)}}
        if method == "getMe":
            return {"ok": True, "result": {"username": "test_bot"}}
        if method == "sendChatAction":
            return {"ok": True}
        return {"ok": True, "result": {}}

    # Patch in the actual submodule where it's called
    _telegram = sys.modules["notify.telegram"]
    _approval = sys.modules["notify.approval"]
    _replies = sys.modules["notify.replies"]
    monkeypatch.setattr(_telegram, "_telegram_api", fake_api)
    if hasattr(_approval, "_telegram_api"):
        monkeypatch.setattr(_approval, "_telegram_api", fake_api)
    if hasattr(_replies, "_telegram_api"):
        monkeypatch.setattr(_replies, "_telegram_api", fake_api)

    return calls


@pytest.fixture()
def enable_notifications(notify: Any, tmp_path: Path) -> Path:  # noqa: ARG001
    """Create a sentinel file to enable notifications."""
    sentinel = tmp_path / "notify-enabled"
    sentinel.write_text(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return sentinel


@pytest.fixture()
def sample_stop_event() -> dict[str, Any]:
    """A minimal Stop event."""
    return {
        "hook_event_name": "Stop",
        "cwd": "/test/demo-project",
        "stop_hook_active": False,
    }


@pytest.fixture()
def sample_notification_event() -> dict[str, Any]:
    """A minimal Notification event."""
    return {
        "hook_event_name": "Notification",
        "cwd": "/test/demo-project",
        "message": "Build finished successfully",
    }


@pytest.fixture()
def sample_task_event() -> dict[str, Any]:
    """A minimal TaskCompleted event."""
    return {
        "hook_event_name": "TaskCompleted",
        "cwd": "/test/demo-project",
        "task_id": "3",
        "task_description": "Implement authentication module",
    }
