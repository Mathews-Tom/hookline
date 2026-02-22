"""Tests for state management: CRUD, locking, atomic writes."""
from __future__ import annotations

from typing import Any


class TestReadWriteState:
    """Test _read_state and _write_state."""

    def test_write_then_read(self, hookline: Any) -> None:
        hookline._write_state("proj", "test.json", {"key": "value"})
        result = hookline._read_state("proj", "test.json")
        assert result == {"key": "value"}

    def test_read_missing_returns_empty(self, hookline: Any) -> None:
        result = hookline._read_state("proj", "nonexistent.json")
        assert result == {}

    def test_clear_state(self, hookline: Any) -> None:
        hookline._write_state("proj", "test.json", {"a": 1})
        hookline._clear_state("proj", "test.json")
        assert hookline._read_state("proj", "test.json") == {}

    def test_state_dir_created_automatically(self, hookline: Any) -> None:
        d = hookline._state_dir("new-project")
        assert d.exists()
        assert d.is_dir()

    def test_global_project_uses_underscore(self, hookline: Any) -> None:
        d = hookline._state_dir("")
        assert d.name == "_global"


class TestLockedUpdate:
    """Test _locked_update for atomic read-modify-write."""

    def test_update_new_file(self, hookline: Any) -> None:
        def updater(state: dict) -> dict:
            state["count"] = state.get("count", 0) + 1
            return state

        result = hookline._locked_update("proj", "counter.json", updater)
        assert result == {"count": 1}

    def test_update_existing_file(self, hookline: Any) -> None:
        hookline._write_state("proj", "counter.json", {"count": 5})

        def updater(state: dict) -> dict:
            state["count"] = state.get("count", 0) + 1
            return state

        result = hookline._locked_update("proj", "counter.json", updater)
        assert result == {"count": 6}

    def test_updater_returns_none_deletes_file(self, hookline: Any) -> None:
        hookline._write_state("proj", "temp.json", {"data": True})

        def updater(state: dict) -> None:
            return None

        hookline._locked_update("proj", "temp.json", updater)
        assert hookline._read_state("proj", "temp.json") == {}
