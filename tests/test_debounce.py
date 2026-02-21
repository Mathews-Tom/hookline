"""Tests for debounce accumulation and flushing."""
from __future__ import annotations

import time
from typing import Any

import pytest


class TestDebounceAccumulate:
    """Test _debounce_accumulate batching."""

    def test_accumulates_subagent_events(self, notify: Any) -> None:
        event = {"hook_event_name": "SubagentStop", "cwd": "/test/proj"}
        notify._debounce_accumulate("proj", event)
        state = notify._read_state("proj", "debounce.json")
        assert state["events"]["SubagentStop"]["count"] == 1

    def test_accumulates_multiple_events(self, notify: Any) -> None:
        event = {"hook_event_name": "SubagentStop", "cwd": "/test/proj"}
        notify._debounce_accumulate("proj", event)
        notify._debounce_accumulate("proj", event)
        state = notify._read_state("proj", "debounce.json")
        assert state["events"]["SubagentStop"]["count"] == 2

    def test_tracks_teammate_names(self, notify: Any) -> None:
        event1 = {"hook_event_name": "TeammateIdle", "teammate_name": "researcher"}
        event2 = {"hook_event_name": "TeammateIdle", "teammate_name": "tester"}
        notify._debounce_accumulate("proj", event1)
        notify._debounce_accumulate("proj", event2)
        state = notify._read_state("proj", "debounce.json")
        names = set(state["events"]["TeammateIdle"]["names"])
        assert names == {"researcher", "tester"}


class TestDebounceFlush:
    """Test _debounce_flush output."""

    def test_flush_empty_returns_none(self, notify: Any) -> None:
        assert notify._debounce_flush("proj") is None

    def test_flush_returns_html(self, notify: Any) -> None:
        event = {"hook_event_name": "SubagentStop", "cwd": "/test/proj"}
        notify._debounce_accumulate("proj", event)
        result = notify._debounce_flush("proj")
        assert result is not None
        assert "subagent" in result.lower()

    def test_flush_clears_state(self, notify: Any) -> None:
        event = {"hook_event_name": "SubagentStop", "cwd": "/test/proj"}
        notify._debounce_accumulate("proj", event)
        notify._debounce_flush("proj")
        assert notify._read_state("proj", "debounce.json") == {}


class TestDebounceShouldFlush:
    """Test _debounce_should_flush timing."""

    def test_no_state_returns_false(self, notify: Any) -> None:
        assert notify._debounce_should_flush("proj") is False

    def test_recent_returns_false(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        notify._write_state("proj", "debounce.json", {
            "events": {"SubagentStop": {"count": 1, "names": []}},
            "last_time": time.time(),
        })
        assert notify._debounce_should_flush("proj") is False

    def test_old_returns_true(self, notify: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        notify._write_state("proj", "debounce.json", {
            "events": {"SubagentStop": {"count": 1, "names": []}},
            "last_time": time.time() - 60,
        })
        assert notify._debounce_should_flush("proj") is True
