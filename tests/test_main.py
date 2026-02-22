"""Integration tests for main event routing and gate checks."""
from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from typing import Any

import pytest


class TestMainEventRouting:
    """Test main() dispatches events correctly."""

    def _run_main(self, event: dict, monkeypatch: pytest.MonkeyPatch) -> None:
        """Helper to call main() with event on stdin."""
        from hookline.__main__ import main
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps(event)))
        main()

    def test_stop_event_sends_message(
        self, hookline: Any, mock_telegram: list, enable_notifications: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event = {"hook_event_name": "Stop", "cwd": "/test/demo-project", "stop_hook_active": False}
        self._run_main(event, monkeypatch)
        send_calls = [c for c in mock_telegram if c[0] == "sendMessage"]
        assert len(send_calls) >= 1

    def test_notification_event_sends_message(
        self, hookline: Any, mock_telegram: list, enable_notifications: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event = {"hook_event_name": "Notification", "cwd": "/test/proj", "message": "Hello"}
        self._run_main(event, monkeypatch)
        send_calls = [c for c in mock_telegram if c[0] == "sendMessage"]
        assert len(send_calls) >= 1

    def test_disabled_project_sends_nothing(
        self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.__main__ import main
        event = {"hook_event_name": "Stop", "cwd": "/test/proj", "stop_hook_active": False}
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps(event)))
        main()
        assert len(mock_telegram) == 0

    def test_suppressed_event_sends_nothing(
        self, hookline: Any, mock_telegram: list, enable_notifications: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline import __main__ as _main_mod
        monkeypatch.setattr(_main_mod, "SUPPRESS", {"Stop"})
        event = {"hook_event_name": "Stop", "cwd": "/test/proj", "stop_hook_active": False}
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps(event)))
        _main_mod.main()
        assert len(mock_telegram) == 0

    def test_empty_stdin_does_nothing(
        self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.__main__ import main
        monkeypatch.setattr("sys.stdin", StringIO(""))
        main()
        assert len(mock_telegram) == 0

    def test_invalid_json_does_nothing(
        self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.__main__ import main
        monkeypatch.setattr("sys.stdin", StringIO("not json"))
        main()
        assert len(mock_telegram) == 0

    def test_debounce_event_accumulates(
        self, hookline: Any, mock_telegram: list, enable_notifications: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        event = {"hook_event_name": "SubagentStop", "cwd": "/test/proj"}
        self._run_main(event, monkeypatch)
        assert len(mock_telegram) == 0


class TestDryRun:
    """Test --dry-run mode."""

    def test_dry_run_prints_to_stdout(
        self, hookline: Any, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    ) -> None:
        from hookline import __main__ as _main_mod
        from hookline import telegram as _telegram
        monkeypatch.setattr(_main_mod, "DRY_RUN", True)
        monkeypatch.setattr(_telegram, "DRY_RUN", True)
        event = {"hook_event_name": "Stop", "cwd": "/test/proj", "stop_hook_active": False}
        monkeypatch.setattr("sys.stdin", StringIO(json.dumps(event)))
        _main_mod.main()
        captured = capsys.readouterr()
        assert "[dry-run]" in captured.out
        assert "Stop" in captured.out


class TestVersion:
    """Test version attribute."""

    def test_version_exists(self, hookline: Any) -> None:
        assert hasattr(hookline, "__version__")
        assert isinstance(hookline.__version__, str)
        assert "." in hookline.__version__
