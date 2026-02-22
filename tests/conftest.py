"""Shared fixtures for hookline tests."""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


@pytest.fixture()
def _add_project_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """Add the project root to sys.path so we can import hookline."""
    root = str(Path(__file__).resolve().parent.parent)
    if root not in sys.path:
        monkeypatch.syspath_prepend(root)


@pytest.fixture()
def hookline(_add_project_root: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:  # noqa: ARG001
    """Import hookline package with sandboxed state directory and no real Telegram calls."""
    import hookline as _hookline

    # __init__.py re-exports shadow submodule names (e.g., hookline.serve = function).
    # Use sys.modules to get the actual module objects.
    def _submod(name: str) -> ModuleType:
        importlib.import_module(f"hookline.{name}")
        return sys.modules[f"hookline.{name}"]

    _config = _submod("config")
    _state = _submod("state")
    _session = _submod("session")
    _project = _submod("project")
    _transcript = _submod("transcript")
    _telegram = _submod("telegram")
    _approval = _submod("approval")
    _serve = _submod("serve")
    _debounce = _submod("debounce")
    _relay = _submod("relay")
    _commands = _submod("commands")
    _proactive = _submod("proactive")

    state_dir = tmp_path / "hookline-state"
    state_dir.mkdir()
    pid_file = state_dir / "serve.pid"
    memory_db = str(state_dir / "memory.db")

    # All submodules that need patching
    _main = _submod("__main__")
    _threads = _submod("threads")
    _replies = _submod("replies")
    all_mods = [
        _config, _state, _session, _project, _transcript, _telegram,
        _approval, _serve, _debounce, _main, _threads, _replies,
        _relay, _commands, _proactive,
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
        "MEMORY_ENABLED": False,
        "MEMORY_DB_PATH": memory_db,
        "MEMORY_MAX_ENTRIES": 1000,
        "SCHEDULE_ENABLED": False,
    }
    for attr, value in patches.items():
        for mod in all_mods:
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, value)

    # Clear caches
    monkeypatch.setattr(_config, "_hookline_config", None)
    monkeypatch.setattr(_project, "_project_config", None)
    monkeypatch.setattr(_transcript, "_transcript_cache", {})

    # Reset memory store singleton
    _memory_store = _submod("memory.store")
    monkeypatch.setattr(_memory_store, "_store_instance", None)

    # Reset scheduler registry
    _scheduler = _submod("scheduler")
    monkeypatch.setattr(_scheduler, "_tasks", {})
    monkeypatch.setattr(_scheduler, "_SCHEDULE_STATE_FILE", state_dir / "scheduler.json")

    # Patch the re-exports on the package itself for direct access
    for attr, value in patches.items():
        if hasattr(_hookline, attr):
            monkeypatch.setattr(_hookline, attr, value)

    return _hookline


@pytest.fixture()
def mock_telegram(
    hookline: Any, monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, dict[str, Any]]]:
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

    # Patch in every submodule that imports _telegram_api
    api_modules = [
        "hookline.telegram", "hookline.approval", "hookline.replies",
        "hookline.commands", "hookline.serve", "hookline.proactive",
    ]
    for mod_name in api_modules:
        mod = sys.modules.get(mod_name)
        if mod and hasattr(mod, "_telegram_api"):
            monkeypatch.setattr(mod, "_telegram_api", fake_api)

    return calls


@pytest.fixture()
def enable_notifications(hookline: Any, tmp_path: Path) -> Path:  # noqa: ARG001
    """Create a sentinel file to enable notifications."""
    sentinel = tmp_path / "hookline-enabled"
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
