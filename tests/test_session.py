"""Tests for session management: sentinel, mute, enabled check."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TestSentinel:
    """Test sentinel file detection and parsing."""

    def test_no_sentinel_returns_none(self, hookline: Any) -> None:
        assert hookline._sentinel_path("nonexistent") is None

    def test_project_sentinel_found(self, hookline: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "hookline-enabled.myproj"
        sentinel.write_text("2025-01-01T00:00:00Z")
        result = hookline._sentinel_path("myproj")
        assert result == sentinel

    def test_global_sentinel_found(self, hookline: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "hookline-enabled"
        sentinel.write_text("2025-01-01T00:00:00Z")
        result = hookline._sentinel_path("anyproj")
        assert result == sentinel

    def test_project_sentinel_preferred_over_global(self, hookline: Any, tmp_path: Path) -> None:
        (tmp_path / "hookline-enabled").write_text("2025-01-01T00:00:00Z")
        proj_sentinel = tmp_path / "hookline-enabled.myproj"
        proj_sentinel.write_text("2025-01-02T00:00:00Z")
        result = hookline._sentinel_path("myproj")
        assert result == proj_sentinel


class TestSentinelTimestamp:
    """Test _sentinel_timestamp helper."""

    def test_returns_datetime(self, hookline: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "hookline-enabled.proj"
        sentinel.write_text("2025-06-15T12:30:00Z")
        result = hookline._sentinel_timestamp("proj")
        assert isinstance(result, datetime)
        assert result.year == 2025

    def test_returns_none_for_missing(self, hookline: Any) -> None:
        assert hookline._sentinel_timestamp("missing") is None

    def test_returns_none_for_invalid(self, hookline: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "hookline-enabled.proj"
        sentinel.write_text("not-a-date")
        assert hookline._sentinel_timestamp("proj") is None


class TestSessionKey:
    """Test _session_key."""

    def test_returns_sentinel_content(self, hookline: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "hookline-enabled.proj"
        sentinel.write_text("2025-01-01T00:00:00Z")
        assert hookline._session_key("proj") == "2025-01-01T00:00:00Z"

    def test_returns_unknown_when_missing(self, hookline: Any) -> None:
        assert hookline._session_key("missing") == "unknown"


class TestSessionDuration:
    """Test _session_duration."""

    def test_recent_session_shows_seconds(self, hookline: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "hookline-enabled.proj"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sentinel.write_text(now)
        result = hookline._session_duration("proj")
        assert result is not None
        assert result.endswith("s")

    def test_returns_none_for_missing(self, hookline: Any) -> None:
        assert hookline._session_duration("missing") is None


class TestMute:
    """Test mute checking."""

    def test_not_muted_by_default(self, hookline: Any) -> None:
        assert hookline._is_muted("proj") is False

    def test_muted_when_future_timestamp(self, hookline: Any) -> None:
        hookline._write_state("proj", "mute.json", {"until": time.time() + 1800})
        assert hookline._is_muted("proj") is True

    def test_unmuted_when_expired(self, hookline: Any) -> None:
        hookline._write_state("proj", "mute.json", {"until": time.time() - 10})
        assert hookline._is_muted("proj") is False


class TestIsEnabled:
    """Test _is_enabled gate."""

    def test_disabled_when_no_sentinel(self, hookline: Any) -> None:
        assert hookline._is_enabled("proj") is False

    def test_enabled_with_sentinel(self, hookline: Any, enable_notifications: Path) -> None:
        # enable_notifications creates the global sentinel
        assert hookline._is_enabled("proj") is True

    def test_disabled_when_muted(self, hookline: Any, enable_notifications: Path) -> None:
        hookline._write_state("proj", "mute.json", {"until": time.time() + 1800})
        assert hookline._is_enabled("proj") is False
