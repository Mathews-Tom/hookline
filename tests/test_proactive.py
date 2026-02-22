"""Tests for scheduler engine and proactive features."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

# ── CronExpr Tests ───────────────────────────────────────────────────────────


class TestCronExpr:
    """Test cron expression parsing and matching."""

    def test_wildcard_matches_any(self) -> None:
        from hookline.scheduler import CronExpr
        expr = CronExpr("* * * * *")
        dt = datetime(2025, 6, 15, 14, 30, tzinfo=timezone.utc)
        assert expr.matches(dt)

    def test_exact_minute_hour(self) -> None:
        from hookline.scheduler import CronExpr
        expr = CronExpr("30 9 * * *")
        assert expr.matches(datetime(2025, 6, 15, 9, 30, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2025, 6, 15, 9, 31, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2025, 6, 15, 10, 30, tzinfo=timezone.utc))

    def test_range(self) -> None:
        from hookline.scheduler import CronExpr
        expr = CronExpr("0 9 * * 0-4")  # Mon-Fri (0=Mon in Python)
        # 2025-06-16 is a Monday (weekday=0)
        assert expr.matches(datetime(2025, 6, 16, 9, 0, tzinfo=timezone.utc))
        # 2025-06-21 is a Saturday (weekday=5)
        assert not expr.matches(datetime(2025, 6, 21, 9, 0, tzinfo=timezone.utc))

    def test_step(self) -> None:
        from hookline.scheduler import CronExpr
        expr = CronExpr("*/15 * * * *")  # Every 15 minutes
        assert expr.matches(datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc))
        assert expr.matches(datetime(2025, 6, 15, 10, 15, tzinfo=timezone.utc))
        assert expr.matches(datetime(2025, 6, 15, 10, 30, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2025, 6, 15, 10, 7, tzinfo=timezone.utc))

    def test_list(self) -> None:
        from hookline.scheduler import CronExpr
        expr = CronExpr("0 9,18 * * *")  # 9am and 6pm
        assert expr.matches(datetime(2025, 6, 15, 9, 0, tzinfo=timezone.utc))
        assert expr.matches(datetime(2025, 6, 15, 18, 0, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc))

    def test_invalid_field_count(self) -> None:
        from hookline.scheduler import CronExpr
        with pytest.raises(ValueError, match="5 fields"):
            CronExpr("* * *")

    def test_invalid_range(self) -> None:
        from hookline.scheduler import CronExpr
        with pytest.raises(ValueError, match="Invalid range"):
            CronExpr("30-10 * * * *")

    def test_out_of_range_value(self) -> None:
        from hookline.scheduler import CronExpr
        with pytest.raises(ValueError, match="out of range"):
            CronExpr("60 * * * *")

    def test_invalid_step(self) -> None:
        from hookline.scheduler import CronExpr
        with pytest.raises(ValueError, match="Step must be positive"):
            CronExpr("*/0 * * * *")

    def test_dom_and_month(self) -> None:
        from hookline.scheduler import CronExpr
        expr = CronExpr("0 0 1 1 *")  # Midnight on Jan 1st
        assert expr.matches(datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2025, 1, 2, 0, 0, tzinfo=timezone.utc))
        assert not expr.matches(datetime(2025, 2, 1, 0, 0, tzinfo=timezone.utc))


# ── ScheduledTask Tests ──────────────────────────────────────────────────────


class TestScheduledTask:
    """Test scheduled task trigger logic."""

    def test_cron_task_fires(self) -> None:
        from hookline.scheduler import ScheduledTask
        called = []
        task = ScheduledTask("test", lambda: called.append(1), cron="30 9 * * *")
        now = datetime(2025, 6, 15, 9, 30, tzinfo=timezone.utc)
        assert task.should_run(now, time.time())

    def test_cron_task_no_match(self) -> None:
        from hookline.scheduler import ScheduledTask
        task = ScheduledTask("test", lambda: None, cron="30 9 * * *")
        now = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
        assert not task.should_run(now, time.time())

    def test_cron_no_double_fire(self) -> None:
        from hookline.scheduler import ScheduledTask
        task = ScheduledTask("test", lambda: None, cron="30 9 * * *")
        now = datetime(2025, 6, 15, 9, 30, tzinfo=timezone.utc)
        now_ts = now.timestamp()
        task.last_run = now_ts  # Already ran this minute
        assert not task.should_run(now, now_ts + 5)

    def test_interval_task_fires(self) -> None:
        from hookline.scheduler import ScheduledTask
        task = ScheduledTask("test", lambda: None, interval_minutes=60)
        task.last_run = 0.0  # Never ran
        now = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
        assert task.should_run(now, time.time())

    def test_interval_task_too_early(self) -> None:
        from hookline.scheduler import ScheduledTask
        task = ScheduledTask("test", lambda: None, interval_minutes=60)
        now_ts = time.time()
        task.last_run = now_ts - 30  # Only 30 seconds ago
        now = datetime(2025, 6, 15, 10, 0, tzinfo=timezone.utc)
        assert not task.should_run(now, now_ts)

    def test_requires_cron_or_interval(self) -> None:
        from hookline.scheduler import ScheduledTask
        with pytest.raises(ValueError, match="requires either"):
            ScheduledTask("test", lambda: None)


# ── Scheduler Integration Tests ──────────────────────────────────────────────


class TestSchedulerTick:
    """Test scheduler tick() and state persistence."""

    def test_tick_runs_due_task(
        self,
        hookline: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import hookline.scheduler as sched

        monkeypatch.setattr(sched, "STATE_DIR", tmp_path)
        monkeypatch.setattr(sched, "_SCHEDULE_STATE_FILE", tmp_path / "scheduler.json")
        sched.unregister_all()

        called: list[str] = []
        sched.register_task("test_task", lambda: called.append("ran"), cron="* * * * *")

        sched.tick()
        assert called == ["ran"]

    def test_tick_persists_state(
        self,
        hookline: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import hookline.scheduler as sched

        state_file = tmp_path / "scheduler.json"
        monkeypatch.setattr(sched, "STATE_DIR", tmp_path)
        monkeypatch.setattr(sched, "_SCHEDULE_STATE_FILE", state_file)
        sched.unregister_all()

        sched.register_task("persist_test", lambda: None, cron="* * * * *")
        sched.tick()

        assert state_file.exists()
        state = json.loads(state_file.read_text())
        assert "persist_test" in state
        assert state["persist_test"] > 0

    def test_tick_skips_already_run(
        self,
        hookline: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import hookline.scheduler as sched

        state_file = tmp_path / "scheduler.json"
        monkeypatch.setattr(sched, "STATE_DIR", tmp_path)
        monkeypatch.setattr(sched, "_SCHEDULE_STATE_FILE", state_file)
        sched.unregister_all()

        called: list[str] = []
        sched.register_task("once_test", lambda: called.append("ran"), cron="* * * * *")

        sched.tick()
        sched.tick()  # Second tick should NOT re-run within same minute
        assert called == ["ran"]

    def test_tick_handles_handler_error(
        self,
        hookline: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import hookline.scheduler as sched

        monkeypatch.setattr(sched, "STATE_DIR", tmp_path)
        monkeypatch.setattr(sched, "_SCHEDULE_STATE_FILE", tmp_path / "scheduler.json")
        sched.unregister_all()

        def bad_handler() -> None:
            raise RuntimeError("handler failed")

        sched.register_task("error_test", bad_handler, cron="* * * * *")
        # Should not raise
        sched.tick()

    def test_get_status(
        self,
        hookline: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import hookline.scheduler as sched

        monkeypatch.setattr(sched, "STATE_DIR", tmp_path)
        monkeypatch.setattr(sched, "_SCHEDULE_STATE_FILE", tmp_path / "scheduler.json")
        sched.unregister_all()

        sched.register_task("cron_task", lambda: None, cron="0 9 * * *")
        sched.register_task("interval_task", lambda: None, interval_minutes=30)

        status = sched.get_status()
        assert len(status) == 2
        names = {s["name"] for s in status}
        assert names == {"cron_task", "interval_task"}

    def test_unregister_all(self, hookline: Any) -> None:
        import hookline.scheduler as sched
        sched.register_task("tmp", lambda: None, cron="* * * * *")
        sched.unregister_all()
        assert sched.get_status() == []


# ── Proactive Handler Tests ──────────────────────────────────────────────────


class TestProactiveBriefing:
    """Test morning briefing handler."""

    def test_briefing_sends_message(
        self,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import hookline.proactive as proactive
        monkeypatch.setattr(proactive, "SCHEDULE_ENABLED", True)
        monkeypatch.setattr(proactive, "RELAY_ENABLED", False)
        monkeypatch.setattr(proactive, "MEMORY_ENABLED", False)


        proactive.send_briefing()
        assert len(mock_telegram) >= 1
        text = mock_telegram[-1][1]["text"]
        assert "Briefing" in text

    def test_briefing_includes_sessions(
        self,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import hookline.proactive as proactive

        monkeypatch.setattr(proactive, "SCHEDULE_ENABLED", True)
        monkeypatch.setattr(proactive, "RELAY_ENABLED", True)
        monkeypatch.setattr(proactive, "MEMORY_ENABLED", False)


        # Create a fake active session
        session_dir = tmp_path / "hookline-state" / "test-project" / "relay"
        session_dir.mkdir(parents=True)
        (session_dir / "session.json").write_text(
            json.dumps({"project": "test-project", "started": "2025-01-01T00:00:00Z"})
        )

        proactive.send_briefing()
        sent = [c for c in mock_telegram if c[0] == "sendMessage"]
        assert len(sent) >= 1


class TestProactiveDigest:
    """Test daily digest handler."""

    def test_digest_with_no_data_sends_nothing(
        self,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import hookline.proactive as proactive
        monkeypatch.setattr(proactive, "SCHEDULE_ENABLED", True)
        monkeypatch.setattr(proactive, "RELAY_ENABLED", False)
        monkeypatch.setattr(proactive, "MEMORY_ENABLED", False)


        before = len(mock_telegram)
        proactive.send_digest()
        # No data = no message sent
        assert len(mock_telegram) == before


class TestProactiveCheckin:
    """Test periodic check-in handler."""

    def test_checkin_no_relay_sends_nothing(
        self,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import hookline.proactive as proactive
        monkeypatch.setattr(proactive, "RELAY_ENABLED", False)


        before = len(mock_telegram)
        proactive.send_checkin()
        assert len(mock_telegram) == before

    def test_checkin_no_sessions_sends_nothing(
        self,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import hookline.proactive as proactive
        monkeypatch.setattr(proactive, "RELAY_ENABLED", True)
        monkeypatch.setattr(proactive, "MEMORY_ENABLED", False)


        before = len(mock_telegram)
        proactive.send_checkin()
        assert len(mock_telegram) == before


# ── Setup Tests ──────────────────────────────────────────────────────────────


class TestSetupProactive:
    """Test proactive feature registration."""

    def test_setup_registers_tasks(
        self,
        hookline: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import hookline.proactive as proactive
        import hookline.scheduler as sched

        monkeypatch.setattr(sched, "STATE_DIR", tmp_path)
        monkeypatch.setattr(sched, "_SCHEDULE_STATE_FILE", tmp_path / "scheduler.json")
        sched.unregister_all()

        monkeypatch.setattr(proactive, "SCHEDULE_ENABLED", True)
        monkeypatch.setattr(proactive, "BRIEFING_CRON", "0 9 * * *")
        monkeypatch.setattr(proactive, "DIGEST_CRON", "0 18 * * *")
        monkeypatch.setattr(proactive, "CHECKIN_INTERVAL", 60)

        proactive.setup_proactive()

        status = sched.get_status()
        names = {s["name"] for s in status}
        assert "briefing" in names
        assert "digest" in names
        assert "checkin" in names

    def test_setup_disabled_registers_nothing(
        self,
        hookline: Any,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import hookline.proactive as proactive
        import hookline.scheduler as sched

        monkeypatch.setattr(sched, "STATE_DIR", tmp_path)
        monkeypatch.setattr(sched, "_SCHEDULE_STATE_FILE", tmp_path / "scheduler.json")
        sched.unregister_all()

        monkeypatch.setattr(proactive, "SCHEDULE_ENABLED", False)
        proactive.setup_proactive()

        assert sched.get_status() == []


# ── Command Tests ────────────────────────────────────────────────────────────


class TestProactiveCommands:
    """Test schedule-related Telegram commands."""

    def test_schedule_command_disabled(
        self,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import hookline.commands as commands
        monkeypatch.setattr(commands, "SCHEDULE_ENABLED", False)
        commands.dispatch("schedule", "test-proj", "", 1)
        assert any("disabled" in c[1].get("text", "").lower() for c in mock_telegram)

    def test_schedule_command_shows_tasks(
        self,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        import hookline.commands as commands
        import hookline.scheduler as sched

        monkeypatch.setattr(commands, "SCHEDULE_ENABLED", True)
        monkeypatch.setattr(sched, "STATE_DIR", tmp_path)
        monkeypatch.setattr(sched, "_SCHEDULE_STATE_FILE", tmp_path / "scheduler.json")
        sched.unregister_all()
        sched.register_task("test_task", lambda: None, cron="0 9 * * *")

        commands.dispatch("schedule", "test-proj", "", 1)
        text = mock_telegram[-1][1].get("text", "")
        assert "test_task" in text

    def test_digest_command_disabled(
        self,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import hookline.commands as commands
        monkeypatch.setattr(commands, "SCHEDULE_ENABLED", False)
        commands.dispatch("digest", "test-proj", "", 1)
        assert any("disabled" in c[1].get("text", "").lower() for c in mock_telegram)

    def test_briefing_command_disabled(
        self,
        mock_telegram: list[tuple[str, dict[str, Any]]],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import hookline.commands as commands
        monkeypatch.setattr(commands, "SCHEDULE_ENABLED", False)
        commands.dispatch("briefing", "test-proj", "", 1)
        assert any("disabled" in c[1].get("text", "").lower() for c in mock_telegram)
