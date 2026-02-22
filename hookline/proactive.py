"""Proactive feature handlers: briefing, digest, check-in."""
from __future__ import annotations

from datetime import datetime, timezone

from hookline._log import log
from hookline.config import (
    BRIEFING_CRON,
    CHAT_ID,
    CHECKIN_INTERVAL,
    DIGEST_CRON,
    MEMORY_ENABLED,
    RELAY_ENABLED,
    SCHEDULE_ENABLED,
)
from hookline.formatting import _esc, _truncate
from hookline.telegram import _telegram_api


def setup_proactive() -> None:
    """Register proactive tasks with the scheduler based on config.

    Called once at serve daemon startup when SCHEDULE_ENABLED is True.
    """
    if not SCHEDULE_ENABLED:
        return

    from hookline.scheduler import register_task

    if BRIEFING_CRON:
        register_task("briefing", send_briefing, cron=BRIEFING_CRON)

    if DIGEST_CRON:
        register_task("digest", send_digest, cron=DIGEST_CRON)

    if CHECKIN_INTERVAL and CHECKIN_INTERVAL > 0:
        register_task("checkin", send_checkin, interval_minutes=CHECKIN_INTERVAL)


def send_briefing() -> None:
    """Send a morning briefing with goals, active sessions, and pending items."""
    lines: list[str] = [f"<b>Morning Briefing</b>  {_now_label()}", ""]

    # Active sessions
    if RELAY_ENABLED:
        from hookline.relay import list_active_sessions
        sessions = list_active_sessions()
        if sessions:
            lines.append(f"<b>Sessions</b> ({len(sessions)} active):")
            for s in sessions[:5]:
                status = " (paused)" if s.get("paused") else ""
                lines.append(f"  {_esc(s['project'])}{status}")
        else:
            lines.append("No active sessions.")
    else:
        lines.append("Relay disabled — no session tracking.")

    # Active goals from memory
    if MEMORY_ENABLED:
        try:
            from hookline.memory.store import get_store
            store = get_store()
            goals = store.get_knowledge("", category="goal", active_only=True)
            if goals:
                lines.append("")
                lines.append(f"<b>Active Goals</b> ({len(goals)}):")
                for g in goals[:5]:
                    proj = g.get("project", "?")
                    text = _truncate(g.get("text", ""), 120)
                    lines.append(f"  [{_esc(proj)}] {_esc(text)}")
        except Exception as e:
            log(f"Briefing memory error: {e}")

    # Pending approvals
    _append_pending_approvals(lines)

    if len(lines) <= 2:
        return  # Nothing to report

    _send_proactive("\n".join(lines))


def send_digest() -> None:
    """Send a daily digest summarizing project activity."""
    lines: list[str] = [f"<b>Daily Digest</b>  {_now_label()}", ""]

    has_content = False

    # Session summary
    if RELAY_ENABLED:
        from hookline.relay import list_active_sessions
        sessions = list_active_sessions()
        if sessions:
            lines.append(f"<b>Sessions</b>: {len(sessions)} active")
            for s in sessions[:5]:
                parts: list[str] = []
                if s.get("paused"):
                    parts.append("paused")
                unread = s.get("unread_inbox", 0)
                if unread:
                    parts.append(f"{unread} unread")
                extra = f" ({', '.join(parts)})" if parts else ""
                lines.append(f"  {_esc(s['project'])}{extra}")
            has_content = True

    # Memory stats
    if MEMORY_ENABLED:
        try:
            from hookline.memory.store import get_store
            store = get_store()
            stats = store.get_stats()
            if stats.get("total_messages", 0) > 0:
                lines.append("")
                lines.append("<b>Memory</b>:")
                lines.append(f"  Messages: {stats.get('total_messages', 0)}")
                lines.append(f"  Knowledge: {stats.get('total_knowledge', 0)}")
                active_goals = stats.get("active_goals", 0)
                if active_goals:
                    lines.append(f"  Active goals: {active_goals}")
                has_content = True
        except Exception as e:
            log(f"Digest memory error: {e}")

    if not has_content:
        return  # Nothing worth reporting

    _send_proactive("\n".join(lines))


def send_checkin() -> None:
    """Send a periodic check-in if there's something noteworthy.

    Only sends when active sessions exist and there's actionable information
    (unread messages, active goals, paused sessions).
    """
    if not RELAY_ENABLED:
        return

    from hookline.relay import list_active_sessions
    sessions = list_active_sessions()
    if not sessions:
        return

    # Collect noteworthy items
    noteworthy: list[str] = []
    for s in sessions:
        parts: list[str] = []
        if s.get("paused"):
            parts.append("paused")
        unread = s.get("unread_inbox", 0)
        if unread:
            parts.append(f"{unread} unread")
        if parts:
            noteworthy.append(f"  {_esc(s['project'])}: {', '.join(parts)}")

    # Check for active goals
    goal_count = 0
    if MEMORY_ENABLED:
        try:
            from hookline.memory.store import get_store
            store = get_store()
            goals = store.get_knowledge("", category="goal", active_only=True)
            goal_count = len(goals)
        except Exception as e:
            log(f"Checkin memory error: {e}")

    # Only send if there's something actionable
    if not noteworthy and goal_count == 0:
        return

    lines: list[str] = [f"<b>Check-in</b>  {_now_label()}", ""]
    lines.append(f"{len(sessions)} active session(s)")

    if noteworthy:
        lines.extend(noteworthy)

    if goal_count:
        lines.append(f"{goal_count} active goal(s)")

    _send_proactive("\n".join(lines))


def _now_label() -> str:
    """Return a short UTC time label for message headers."""
    return datetime.now(timezone.utc).strftime("%H:%M UTC")


def _append_pending_approvals(lines: list[str]) -> None:
    """Append pending approval count to message lines if any exist."""
    from hookline.config import APPROVAL_ENABLED, STATE_DIR

    if not APPROVAL_ENABLED:
        return

    try:
        approvals_dir = STATE_DIR
        count = 0
        if approvals_dir.exists():
            for project_dir in approvals_dir.iterdir():
                if not project_dir.is_dir():
                    continue
                approval_file = project_dir / "approval.json"
                if approval_file.exists():
                    count += 1
        if count:
            lines.append("")
            lines.append(f"<b>Pending Approvals</b>: {count}")
    except Exception as e:
        log(f"Approval check error: {e}")


def _send_proactive(text: str) -> None:
    """Send a proactive message to the configured chat."""
    _telegram_api("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    })
