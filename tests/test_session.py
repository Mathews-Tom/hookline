"""Tests for session management: sentinel, mute, enabled check."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class TestSentinel:
    """Test sentinel file detection and parsing."""

    def test_no_sentinel_returns_none(self, notify: Any) -> None:
        assert notify._sentinel_path("nonexistent") is None

    def test_project_sentinel_found(self, notify: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "notify-enabled.myproj"
        sentinel.write_text("2025-01-01T00:00:00Z")
        result = notify._sentinel_path("myproj")
        assert result == sentinel

    def test_global_sentinel_found(self, notify: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "notify-enabled"
        sentinel.write_text("2025-01-01T00:00:00Z")
        result = notify._sentinel_path("anyproj")
        assert result == sentinel

    def test_project_sentinel_preferred_over_global(self, notify: Any, tmp_path: Path) -> None:
        (tmp_path / "notify-enabled").write_text("2025-01-01T00:00:00Z")
        proj_sentinel = tmp_path / "notify-enabled.myproj"
        proj_sentinel.write_text("2025-01-02T00:00:00Z")
        result = notify._sentinel_path("myproj")
        assert result == proj_sentinel


class TestSentinelTimestamp:
    """Test _sentinel_timestamp helper."""

    def test_returns_datetime(self, notify: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "notify-enabled.proj"
        sentinel.write_text("2025-06-15T12:30:00Z")
        result = notify._sentinel_timestamp("proj")
        assert isinstance(result, datetime)
        assert result.year == 2025

    def test_returns_none_for_missing(self, notify: Any) -> None:
        assert notify._sentinel_timestamp("missing") is None

    def test_returns_none_for_invalid(self, notify: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "notify-enabled.proj"
        sentinel.write_text("not-a-date")
        assert notify._sentinel_timestamp("proj") is None


class TestSessionKey:
    """Test _session_key."""

    def test_returns_sentinel_content(self, notify: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "notify-enabled.proj"
        sentinel.write_text("2025-01-01T00:00:00Z")
        assert notify._session_key("proj") == "2025-01-01T00:00:00Z"

    def test_returns_unknown_when_missing(self, notify: Any) -> None:
        assert notify._session_key("missing") == "unknown"


class TestSessionDuration:
    """Test _session_duration."""

    def test_recent_session_shows_seconds(self, notify: Any, tmp_path: Path) -> None:
        sentinel = tmp_path / "notify-enabled.proj"
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        sentinel.write_text(now)
        result = notify._session_duration("proj")
        assert result is not None
        assert result.endswith("s")

    def test_returns_none_for_missing(self, notify: Any) -> None:
        assert notify._session_duration("missing") is None


class TestMute:
    """Test mute checking."""

    def test_not_muted_by_default(self, notify: Any) -> None:
        assert notify._is_muted("proj") is False

    def test_muted_when_future_timestamp(self, notify: Any) -> None:
        notify._write_state("proj", "mute.json", {"until": time.time() + 1800})
        assert notify._is_muted("proj") is True

    def test_unmuted_when_expired(self, notify: Any) -> None:
        notify._write_state("proj", "mute.json", {"until": time.time() - 10})
        assert notify._is_muted("proj") is False


class TestIsEnabled:
    """Test _is_enabled gate."""

    def test_disabled_when_no_sentinel(self, notify: Any) -> None:
        assert notify._is_enabled("proj") is False

    def test_enabled_with_sentinel(self, notify: Any, enable_notifications: Path) -> None:
        # enable_notifications creates the global sentinel
        assert notify._is_enabled("proj") is True

    def test_disabled_when_muted(self, notify: Any, enable_notifications: Path) -> None:
        notify._write_state("proj", "mute.json", {"until": time.time() + 1800})
        assert notify._is_enabled("proj") is False
