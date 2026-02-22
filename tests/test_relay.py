"""Tests for relay inbox queue and session management."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


class TestWriteInbox:
    """Test write_inbox appends messages to JSONL."""

    def test_write_creates_file(self, hookline: Any) -> None:
        from hookline.relay import _inbox_path, write_inbox
        msg_id = write_inbox("test-proj", "user", "hello world")
        path = _inbox_path("test-proj")
        assert path.exists()
        assert len(msg_id) == 12

    def test_write_appends_multiple(self, hookline: Any) -> None:
        from hookline.relay import _inbox_path, write_inbox
        write_inbox("test-proj", "alice", "msg1")
        write_inbox("test-proj", "bob", "msg2")
        path = _inbox_path("test-proj")
        lines = [l for l in path.read_text().strip().split("\n") if l]
        assert len(lines) == 2

    def test_write_message_format(self, hookline: Any) -> None:
        from hookline.relay import _inbox_path, write_inbox
        msg_id = write_inbox("test-proj", "telegram", "check tests")
        path = _inbox_path("test-proj")
        entry = json.loads(path.read_text().strip())
        assert entry["id"] == msg_id
        assert entry["sender"] == "telegram"
        assert entry["text"] == "check tests"
        assert entry["read"] is False
        assert "ts" in entry


class TestReadInbox:
    """Test read_inbox retrieves messages."""

    def test_read_empty_project(self, hookline: Any) -> None:
        from hookline.relay import read_inbox
        assert read_inbox("nonexistent") == []

    def test_read_unread_only(self, hookline: Any) -> None:
        from hookline.relay import read_inbox, write_inbox, mark_read
        write_inbox("proj", "a", "msg1")
        write_inbox("proj", "b", "msg2")
        msg_id = write_inbox("proj", "c", "msg3")
        mark_read("proj", [msg_id])
        unread = read_inbox("proj", unread_only=True)
        assert len(unread) == 2

    def test_read_all_messages(self, hookline: Any) -> None:
        from hookline.relay import read_inbox, write_inbox, mark_read
        write_inbox("proj", "a", "msg1")
        id2 = write_inbox("proj", "b", "msg2")
        mark_read("proj", [id2])
        all_msgs = read_inbox("proj", unread_only=False)
        assert len(all_msgs) == 2


class TestMarkRead:
    """Test mark_read updates message state."""

    def test_mark_specific_messages(self, hookline: Any) -> None:
        from hookline.relay import mark_read, read_inbox, write_inbox
        id1 = write_inbox("proj", "a", "msg1")
        write_inbox("proj", "b", "msg2")
        marked = mark_read("proj", [id1])
        assert marked == 1
        unread = read_inbox("proj", unread_only=True)
        assert len(unread) == 1
        assert unread[0]["text"] == "msg2"

    def test_mark_all(self, hookline: Any) -> None:
        from hookline.relay import mark_read, read_inbox, write_inbox
        write_inbox("proj", "a", "msg1")
        write_inbox("proj", "b", "msg2")
        marked = mark_read("proj")
        assert marked == 2
        assert read_inbox("proj", unread_only=True) == []

    def test_mark_nonexistent_project(self, hookline: Any) -> None:
        from hookline.relay import mark_read
        assert mark_read("nonexistent") == 0


class TestClearInbox:
    """Test clear_inbox removes all messages."""

    def test_clear(self, hookline: Any) -> None:
        from hookline.relay import _inbox_path, clear_inbox, write_inbox
        write_inbox("proj", "a", "msg1")
        clear_inbox("proj")
        assert not _inbox_path("proj").exists()

    def test_clear_nonexistent(self, hookline: Any) -> None:
        from hookline.relay import clear_inbox
        clear_inbox("nonexistent")  # no error


class TestPauseResume:
    """Test pause/resume relay state."""

    def test_pause_sets_state(self, hookline: Any) -> None:
        from hookline.relay import is_paused, set_paused
        set_paused("proj", paused=True, by="telegram")
        assert is_paused("proj") is True

    def test_resume_clears_state(self, hookline: Any) -> None:
        from hookline.relay import is_paused, set_paused
        set_paused("proj", paused=True)
        set_paused("proj", paused=False)
        assert is_paused("proj") is False

    def test_default_not_paused(self, hookline: Any) -> None:
        from hookline.relay import is_paused
        assert is_paused("proj") is False


class TestListActiveSessions:
    """Test list_active_sessions enumerates thread state."""

    def test_no_sessions(self, hookline: Any) -> None:
        from hookline.relay import list_active_sessions
        assert list_active_sessions() == []

    def test_finds_active_session(self, hookline: Any) -> None:
        from hookline.relay import list_active_sessions
        from hookline.state import _write_state
        _write_state("myproject", "thread.json", {"session": "s1", "message_id": 123})
        sessions = list_active_sessions()
        assert len(sessions) == 1
        assert sessions[0]["project"] == "myproject"
        assert sessions[0]["paused"] is False
        assert sessions[0]["unread_inbox"] == 0

    def test_includes_inbox_count(self, hookline: Any) -> None:
        from hookline.relay import list_active_sessions, write_inbox
        from hookline.state import _write_state
        _write_state("proj", "thread.json", {"session": "s1", "message_id": 123})
        write_inbox("proj", "user", "hello")
        sessions = list_active_sessions()
        assert sessions[0]["unread_inbox"] == 1

    def test_skips_internal_dirs(self, hookline: Any) -> None:
        from hookline.relay import list_active_sessions
        from hookline.state import _write_state
        _write_state("_approvals", "thread.json", {"session": "s1", "message_id": 1})
        assert list_active_sessions() == []
