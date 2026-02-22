"""Tests for the extensible command registry."""
from __future__ import annotations

import sys
from typing import Any

import pytest


class TestCommandRegistry:
    """Test command registration and dispatch."""

    def test_register_and_dispatch(self, hookline: Any, mock_telegram: list) -> None:
        from hookline.commands import _registry, dispatch, register

        @register("testcmd")
        def _handler(project: str, args: str, reply_to: int) -> None:
            from hookline.telegram import _telegram_api
            _telegram_api("sendMessage", {
                "chat_id": "12345",
                "text": f"handled: {project} {args}",
                "reply_to_message_id": reply_to,
            })

        assert dispatch("testcmd", "proj", "arg1 arg2", 999)
        assert len(mock_telegram) == 1
        assert "handled: proj arg1 arg2" in mock_telegram[0][1]["text"]

        # Cleanup registry
        _registry.pop("testcmd", None)

    def test_dispatch_unknown_returns_false(self, hookline: Any) -> None:
        from hookline.commands import dispatch
        assert dispatch("nonexistent_cmd_xyz", "proj", "", 1) is False

    def test_dispatch_error_sends_error_message(self, hookline: Any, mock_telegram: list) -> None:
        from hookline.commands import _registry, dispatch, register

        @register("failcmd")
        def _handler(project: str, args: str, reply_to: int) -> None:
            raise ValueError("test error")

        dispatch("failcmd", "proj", "", 1)
        error_calls = [c for c in mock_telegram if "Command error" in c[1].get("text", "")]
        assert len(error_calls) == 1

        _registry.pop("failcmd", None)


class TestRelayCommands:
    """Test built-in relay commands."""

    def test_send_disabled(self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch) -> None:
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "RELAY_ENABLED", False)
        from hookline.commands import dispatch
        dispatch("send", "proj", "hello", 1)
        assert any("disabled" in c[1].get("text", "").lower() for c in mock_telegram)

    def test_send_empty_text(self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch) -> None:
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "RELAY_ENABLED", True)
        from hookline.commands import dispatch
        dispatch("send", "proj", "", 1)
        assert any("usage" in c[1].get("text", "").lower() for c in mock_telegram)

    def test_send_queues_message(self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch) -> None:
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "RELAY_ENABLED", True)
        from hookline.commands import dispatch
        from hookline.relay import read_inbox
        dispatch("send", "proj", "check the tests", 1)
        messages = read_inbox("proj", unread_only=True)
        assert len(messages) == 1
        assert messages[0]["text"] == "check the tests"
        assert any("Queued" in c[1].get("text", "") for c in mock_telegram)

    def test_pause_and_resume(self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch) -> None:
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "RELAY_ENABLED", True)
        from hookline.commands import dispatch
        from hookline.relay import is_paused

        dispatch("pause", "proj", "", 1)
        assert is_paused("proj") is True
        assert any("Paused" in c[1].get("text", "") for c in mock_telegram)

        mock_telegram.clear()
        dispatch("resume", "proj", "", 1)
        assert is_paused("proj") is False
        assert any("Resumed" in c[1].get("text", "") for c in mock_telegram)

    def test_pause_already_paused(self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch) -> None:
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "RELAY_ENABLED", True)
        from hookline.commands import dispatch
        from hookline.relay import set_paused

        set_paused("proj", paused=True)
        dispatch("pause", "proj", "", 1)
        assert any("already paused" in c[1].get("text", "") for c in mock_telegram)

    def test_sessions_empty(self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch) -> None:
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "RELAY_ENABLED", True)
        from hookline.commands import dispatch
        dispatch("sessions", "", "", 1)
        assert any("No active" in c[1].get("text", "") for c in mock_telegram)

    def test_sessions_lists_active(self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch) -> None:
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "RELAY_ENABLED", True)
        from hookline.commands import dispatch
        from hookline.state import _write_state
        _write_state("myproject", "thread.json", {"session": "s1", "message_id": 1})
        dispatch("sessions", "", "", 1)
        assert any("myproject" in c[1].get("text", "") for c in mock_telegram)

    def test_inbox_shows_messages(self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch) -> None:
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "RELAY_ENABLED", True)
        from hookline.commands import dispatch
        from hookline.relay import write_inbox
        write_inbox("proj", "user", "test message")
        dispatch("inbox", "proj", "", 1)
        assert any("test message" in c[1].get("text", "") for c in mock_telegram)

    def test_clear_removes_inbox(self, hookline: Any, mock_telegram: list) -> None:
        from hookline.commands import dispatch
        from hookline.relay import read_inbox, write_inbox
        write_inbox("proj", "user", "msg")
        dispatch("clear", "proj", "", 1)
        assert read_inbox("proj") == []


class TestServeMessageRouting:
    """Test serve daemon message routing."""

    def test_threaded_reply_dispatches_to_commands(
        self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _commands = sys.modules["hookline.commands"]
        monkeypatch.setattr(_commands, "RELAY_ENABLED", True)

        from hookline.state import _write_state
        _write_state("proj", "thread.json", {"session": "s1", "message_id": 100})

        from hookline.serve import _handle_threaded_message
        msg = {"message_id": 50, "from": {"id": "12345"}}
        _handle_threaded_message(msg, "sessions", 100)
        assert any("sendMessage" == c[0] for c in mock_telegram)

    def test_threaded_reply_falls_back_to_legacy(
        self, hookline: Any, mock_telegram: list, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from hookline.state import _write_state
        _write_state("proj", "thread.json", {"session": "s1", "message_id": 100})

        from hookline.serve import _handle_threaded_message
        msg = {
            "message_id": 50,
            "from": {"id": "12345"},
            "text": "help",
            "reply_to_message": {"message_id": 100},
        }
        _handle_threaded_message(msg, "help", 100)
        help_calls = [c for c in mock_telegram if "Reply commands" in c[1].get("text", "")]
        assert len(help_calls) >= 1
