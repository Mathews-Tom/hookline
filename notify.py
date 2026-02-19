#!/usr/bin/env python3
"""
Claude Code Hook → Telegram Notifier (v2)

Rich Telegram notifications for Claude Code lifecycle events with:
  - HTML formatting with box-drawing headers
  - Project emoji mapping (~/.claude/notify-projects.json)
  - Session duration tracking (from sentinel timestamp)
  - SubagentStop/TeammateIdle debouncing (batches rapid-fire events)
  - TaskCompleted progress tracking (Task 3/6)
  - Thread grouping (all session messages under one thread)
  - Inline mute buttons (requires --serve mode)
  - Compact mode for low-value events

Hook events: Stop, Notification, TeammateIdle, TaskCompleted, SubagentStop

Usage (called by Claude Code hooks, not manually):
  echo '{"hook_event_name": "Stop", ...}' | python3 notify.py

Button server (optional, for inline mute buttons):
  python3 notify.py --serve
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Configuration ────────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
SENTINEL_DIR = CLAUDE_DIR
STATE_DIR = CLAUDE_DIR / "notify-state"

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Suppress specific events: CLAUDE_NOTIFY_SUPPRESS="SubagentStop,TeammateIdle"
SUPPRESS = set(os.environ.get("CLAUDE_NOTIFY_SUPPRESS", "").split(",")) - {""}

# Minimum session age before notifications fire (seconds)
MIN_SESSION_AGE = int(os.environ.get("CLAUDE_NOTIFY_MIN_AGE", "0"))

# Show inline mute buttons: CLAUDE_NOTIFY_BUTTONS=1
SHOW_BUTTONS = os.environ.get("CLAUDE_NOTIFY_BUTTONS", "0") == "1"

# Debounce window for rapid-fire events (seconds)
DEBOUNCE_WINDOW = int(os.environ.get("CLAUDE_NOTIFY_DEBOUNCE", "30"))

# Events eligible for debouncing (batched into single message)
DEBOUNCE_EVENTS = {"SubagentStop", "TeammateIdle"}

# Events that get full box-drawing treatment
FULL_FORMAT_EVENTS = {"Stop", "TaskCompleted", "Notification"}

EMOJI = {
    "Stop": "✅",
    "Notification": "⏳",
    "TeammateIdle": "💤",
    "TaskCompleted": "🎯",
    "SubagentStop": "📋",
}

# ── State Management ─────────────────────────────────────────────────────────


def _state_dir(project: str) -> Path:
    """Get or create the state directory for a project."""
    d = STATE_DIR / (project or "_global")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _read_state(project: str, filename: str) -> dict:
    """Read a JSON state file. Returns {} on any error."""
    try:
        return json.loads((_state_dir(project) / filename).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(project: str, filename: str, data: dict) -> None:
    """Write a JSON state file atomically."""
    path = _state_dir(project) / filename
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(data))
        tmp.replace(path)
    except OSError as e:
        _log(f"State write error: {e}")


def _clear_state(project: str, filename: str) -> None:
    """Remove a state file."""
    try:
        (_state_dir(project) / filename).unlink(missing_ok=True)
    except OSError:
        pass


def _locked_update(project: str, filename: str, updater: Callable[[dict], dict | None]) -> dict | None:
    """Atomic read-modify-write with file locking. updater(data) returns new data or None to delete."""
    path = _state_dir(project) / filename
    lock_path = path.with_suffix(".lock")
    lock_path.touch(exist_ok=True)
    fd = lock_path.open("r")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
        result = updater(data)
        if result is None:
            path.unlink(missing_ok=True)
        else:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(result))
            tmp.replace(path)
        return result
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()


# ── Project Config ───────────────────────────────────────────────────────────

PROJECT_CONFIG_PATH = CLAUDE_DIR / "notify-projects.json"

# Cache loaded once per invocation
_project_config: dict | None = None


def _get_project_config() -> dict:
    """Load project config: {"attest": "🧪", "cairn": "🪨", ...}"""
    global _project_config
    if _project_config is None:
        try:
            _project_config = json.loads(PROJECT_CONFIG_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            _project_config = {}
    return _project_config  # type: ignore[return-value]


def _project_emoji(project: str) -> str:
    """Get the emoji for a project, or empty string."""
    return _get_project_config().get(project, "")


def _project_label(project: str) -> str:
    """Format project name with optional emoji: '🧪 attest' or 'attest'."""
    emoji = _project_emoji(project)
    if emoji:
        return f"{emoji} {project}"
    return project


# ── Session Info ─────────────────────────────────────────────────────────────


def _sentinel_path(project: str) -> Path | None:
    """Find the active sentinel file (project-scoped or global)."""
    if project:
        p = SENTINEL_DIR / f"notify-enabled.{project}"
        if p.exists():
            return p
    g = SENTINEL_DIR / "notify-enabled"
    return g if g.exists() else None


def _session_key(project: str) -> str:
    """Unique key for the current session (sentinel creation timestamp)."""
    sentinel = _sentinel_path(project)
    if sentinel:
        try:
            return sentinel.read_text().strip()
        except OSError:
            pass
    return "unknown"


def _session_age_seconds(project: str) -> int | None:
    """Return session age in seconds, or None if unavailable."""
    sentinel = _sentinel_path(project)
    if not sentinel:
        return None
    try:
        ts_str = sentinel.read_text().strip()
        started = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - started
        return int(delta.total_seconds())
    except (OSError, ValueError):
        return None


def _session_duration(project: str) -> str | None:
    """Human-readable session duration from sentinel timestamp."""
    sentinel = _sentinel_path(project)
    if not sentinel:
        return None
    try:
        ts_str = sentinel.read_text().strip()
        started = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - started
        total_sec = int(delta.total_seconds())
        if total_sec < 60:
            return f"{total_sec}s"
        elif total_sec < 3600:
            return f"{total_sec // 60}m"
        else:
            h, m = divmod(total_sec // 60, 60)
            return f"{h}h{m:02d}m"
    except (OSError, ValueError):
        return None


# ── Mute Checking ────────────────────────────────────────────────────────────


def _is_muted(project: str) -> bool:
    """Check if the project is temporarily muted (from inline button press)."""
    mute = _read_state(project, "mute.json")
    until = mute.get("until", 0)
    if until and time.time() < until:
        return True
    elif until:
        # Mute expired — clean up
        _clear_state(project, "mute.json")
    return False


# ── Sentinel Gate ────────────────────────────────────────────────────────────


def _is_enabled(project: str) -> bool:
    """Check if notifications are enabled and not muted."""
    if _sentinel_path(project) is None:
        return False
    if _is_muted(project):
        return False
    return True


# ── Debounce ─────────────────────────────────────────────────────────────────
# SubagentStop/TeammateIdle events are batched within a time window.
# Instead of 4 separate "Subagent finished" messages, you get one:
#   📋 ×4 subagents finished · 🧪 attest · 18:10–18:52 UTC
#
# Flush strategy:
#   - Any invocation: if pending batch is older than DEBOUNCE_WINDOW → flush
#   - Stop event: ALWAYS flush pending (session ending)
#   - Non-debounce event: flush if pending, then send current event
#   - Debounce event: accumulate into batch, don't send


def _debounce_accumulate(project: str, event: dict) -> None:
    """Add a debounce-eligible event to the pending batch."""
    event_name = event.get("hook_event_name", "")
    now = time.time()
    now_utc = datetime.now(timezone.utc).strftime("%H:%M")

    def updater(state: dict) -> dict:
        if not state:
            state = {"events": {}, "first_time": now, "first_utc": now_utc}
        events = state.get("events", {})
        count = events.get(event_name, {}).get("count", 0)
        names = set(events.get(event_name, {}).get("names", []))
        if event_name == "TeammateIdle":
            names.add(event.get("teammate_name", "unknown"))
        events[event_name] = {
            "count": count + 1,
            "names": list(names),
        }
        state["events"] = events
        state["last_time"] = now
        state["last_utc"] = now_utc
        return state

    _locked_update(project, "debounce.json", updater)


def _debounce_flush(project: str) -> str | None:
    """Flush pending debounce batch. Returns formatted HTML or None."""
    flushed: dict = {}

    def updater(state: dict) -> None:
        nonlocal flushed
        flushed = state
        return None  # delete the file

    _locked_update(project, "debounce.json", updater)

    if not flushed or not flushed.get("events"):
        return None

    first_utc = flushed.get("first_utc", "??:??")
    last_utc = flushed.get("last_utc", first_utc)
    time_range = first_utc if first_utc == last_utc else f"{first_utc}–{last_utc}"
    label = _project_label(project)

    parts = []
    for event_name, info in flushed["events"].items():
        count = info["count"]
        emoji = EMOJI.get(event_name, "🔔")
        names = info.get("names", [])
        if event_name == "SubagentStop":
            noun = "subagent" if count == 1 else "subagents"
            parts.append(f"{emoji} ×{count} {noun} finished")
        elif event_name == "TeammateIdle":
            if names:
                name_str = ", ".join(f"<b>{_esc(n)}</b>" for n in sorted(names))
                parts.append(f"{emoji} {name_str} idle")
            else:
                noun = "teammate" if count == 1 else "teammates"
                parts.append(f"{emoji} ×{count} {noun} idle")

    text = " · ".join(parts)
    return f"{text} · {_esc(label)} · <i>{time_range} UTC</i>"


def _debounce_should_flush(project: str) -> bool:
    """Check if there's a pending batch that should be flushed (age > window)."""
    state = _read_state(project, "debounce.json")
    if not state:
        return False
    last = state.get("last_time", 0)
    return (time.time() - last) > DEBOUNCE_WINDOW


# ── Task Tracking ────────────────────────────────────────────────────────────
# Tracks completed tasks per session to show progress: "Task 3/6"


def _track_task(project: str, event: dict) -> tuple[int, int | None]:
    """Record a completed task. Returns (completed_count, total_or_None)."""
    state = _read_state(project, "tasks.json")
    session = _session_key(project)

    # Reset if session changed
    if state.get("session") != session:
        state = {"session": session, "completed": [], "total": None}

    task_id = str(event.get("task_id", ""))
    completed = state.get("completed", [])
    if task_id and task_id not in completed:
        completed.append(task_id)
    state["completed"] = completed

    # Try to infer total from task_id if it's numeric (e.g., "4" of "6")
    # We can't know total from a single event — track cumulative max
    total = state.get("total")
    try:
        num = int(task_id)
        if total is None or num > total:
            state["total"] = num
            total = num
    except (ValueError, TypeError):
        pass

    _write_state(project, "tasks.json", state)
    return len(completed), total


def _clear_tasks(project: str) -> None:
    """Clear task state (called on Stop — session over)."""
    _clear_state(project, "tasks.json")


# ── Thread Management ────────────────────────────────────────────────────────
# Groups all messages from a session under the first message (Telegram threads).


def _get_thread_id(project: str) -> int | None:
    """Get the message_id to reply to for thread grouping."""
    state = _read_state(project, "thread.json")
    session = _session_key(project)
    if state.get("session") == session:
        return state.get("message_id")
    return None


def _set_thread_id(project: str, message_id: int) -> None:
    """Store the first message_id for thread grouping."""
    _write_state(project, "thread.json", {
        "session": _session_key(project),
        "message_id": message_id,
    })


def _clear_thread(project: str) -> None:
    """Clear thread state (called on Stop — session over)."""
    _clear_state(project, "thread.json")


# ── Message Formatting (HTML) ────────────────────────────────────────────────
# Switched from MarkdownV2 to HTML for <blockquote> support and simpler escaping.
#
# Full events (Stop, TaskCompleted, Notification) get box-drawing:
#   ┌─ ✅ Stop ─────── 🧪 attest
#   │ Team disbanded. The report covers...
#   └─ 18:52 UTC ── ⏱ 42m
#
# Compact events (TeammateIdle single) get one-liners:
#   💤 challenger idle · 🧪 attest · 18:50 UTC


def _esc(text: str) -> str:
    """Escape HTML special characters."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _truncate(text: str, max_len: int = 200) -> str:
    """Truncate text with ellipsis."""
    text = text.replace("\n", " ").strip()
    return text[: max_len - 1] + "…" if len(text) > max_len else text


def _log(msg: str) -> None:
    """Log to stderr (visible in Claude Code hook output)."""
    print(f"[claude-notify] {msg}", file=sys.stderr)


def _extract_project(event: dict) -> str:
    """Extract project name from cwd."""
    cwd = event.get("cwd", "")
    return Path(cwd).name if cwd else ""


def _extract_last_message(event: dict) -> str:
    """Try to extract the last assistant message from the transcript."""
    transcript_path = event.get("transcript_path", "")
    if not transcript_path:
        return ""
    path = Path(transcript_path)
    if not path.exists():
        return ""
    try:
        size = path.stat().st_size
        if size > 5 * 1024 * 1024:  # 5MB
            _log(f"Transcript too large ({size} bytes), skipping extraction")
            return ""
        # Read only the last 8KB for efficiency
        tail_size = min(size, 8192)
        with path.open("rb") as f:
            if size > tail_size:
                f.seek(-tail_size, 2)
            raw = f.read().decode("utf-8", errors="replace")
        # Discard partial first line from seek
        lines = raw.split("\n")
        if size > tail_size:
            lines = lines[1:]  # first line is likely partial
        for line in reversed(lines[-20:]):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                msg = entry.get("message", {})
                if msg.get("role") == "assistant":
                    content = msg.get("content", [])
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            return block["text"]
                        if isinstance(block, str):
                            return block
            except (json.JSONDecodeError, AttributeError):
                continue
    except (OSError, PermissionError):
        pass
    return ""


def format_full(event_name: str, event: dict, project: str) -> str:
    """Format a full event with box-drawing headers and blockquote body."""
    emoji = EMOJI.get(event_name, "🔔")
    label = _project_label(project)
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    duration = _session_duration(project)

    # Header
    header = f"<b>┌─ {emoji} {_esc(event_name)} ─────── {_esc(label)}</b>"

    # Body (event-specific)
    body = _format_body(event_name, event, project)

    # Footer with time and duration
    footer_parts = [ts]
    if duration:
        footer_parts.append(f"⏱ {duration}")
    footer = f"<i>└─ {' ── '.join(footer_parts)}</i>"

    return f"{header}\n{body}\n{footer}"


def format_compact(event_name: str, event: dict, project: str) -> str:
    """Format a compact single-line event (TeammateIdle when not debounced)."""
    emoji = EMOJI.get(event_name, "🔔")
    label = _project_label(project)
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if event_name == "TeammateIdle":
        name = event.get("teammate_name", "unknown")
        return f"{emoji} <b>{_esc(name)}</b> idle · {_esc(label)} · <i>{ts}</i>"

    return f"{emoji} {_esc(event_name)} · {_esc(label)} · <i>{ts}</i>"


def _format_body(event_name: str, event: dict, project: str) -> str:
    """Format the body section with blockquote."""
    match event_name:
        case "Stop":
            summary = _extract_last_message(event)
            stop_active = event.get("stop_hook_active", False)
            lines = []
            if summary:
                lines.append(_esc(_truncate(summary, 250)))
            if stop_active:
                lines.append("⚠️ Stop hook was already active")
            if not lines:
                lines.append("Run complete.")
            return "<blockquote>" + "\n".join(lines) + "</blockquote>"

        case "Notification":
            msg = event.get("message", "Needs your attention")
            return f"<blockquote>💬 {_esc(msg)}</blockquote>"

        case "TaskCompleted":
            completed, total = _track_task(project, event)
            desc = event.get("task_description", "")
            task_id = event.get("task_id", "")

            # Progress indicator
            if total and total > 1:
                progress = f"Task {completed}/{total}"
            elif task_id:
                progress = f"Task {_esc(str(task_id))}"
            else:
                progress = "Task completed"

            body_lines = [f"<b>{progress}</b>"]
            if desc:
                body_lines.append(_esc(_truncate(desc, 180)))
            return "<blockquote>" + "\n".join(body_lines) + "</blockquote>"

        case _:
            return f"<blockquote>{_esc(event_name)}</blockquote>"


# ── Telegram Transport ───────────────────────────────────────────────────────


def _telegram_api(method: str, payload: dict, timeout: int = 10) -> dict | None:
    """Call a Telegram Bot API method. Returns parsed JSON or None."""
    if not BOT_TOKEN:
        _log("TELEGRAM_BOT_TOKEN not set")
        return None
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        _log(f"Telegram API [{method}]: {e}")
        return None


def send_message(
    text: str,
    project: str = "",
    reply_to: int | None = None,
) -> int | None:
    """Send an HTML message. Returns message_id on success, None on failure.

    Tries HTML first, falls back to plain text if parsing fails.
    Optionally adds inline mute buttons and reply_to for threading.
    """
    if not BOT_TOKEN or not CHAT_ID:
        _log("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return None

    payload: dict[str, Any] = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        payload["allow_sending_without_reply"] = True

    # Inline mute buttons (only if button server is enabled)
    if SHOW_BUTTONS and project:
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "🔇 Mute 30m", "callback_data": f"mute_30_{project}"},
                {"text": "🔇 Mute Project", "callback_data": f"mute_proj_{project}"},
            ]]
        }

    result = _telegram_api("sendMessage", payload)
    if result and result.get("ok"):
        return result["result"]["message_id"]

    # Fallback: strip HTML and send plain text
    _log("HTML send failed, trying plain text fallback")
    plain = _strip_html(text)
    fallback_payload: dict[str, Any] = {
        "chat_id": CHAT_ID,
        "text": plain,
    }
    if reply_to:
        fallback_payload["reply_to_message_id"] = reply_to
        fallback_payload["allow_sending_without_reply"] = True

    result = _telegram_api("sendMessage", fallback_payload)
    if result and result.get("ok"):
        return result["result"]["message_id"]

    _log("Plain text fallback also failed")
    return None


def _strip_html(text: str) -> str:
    """Crude HTML tag stripper for plain text fallback."""
    import re
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


# ── Button Server ────────────────────────────────────────────────────────────
# Optional companion mode: `python3 notify.py --serve`
# Long-polls Telegram for inline button callbacks and handles:
#   - mute_30_{project}    → mute notifications for 30 minutes
#   - mute_proj_{project}  → remove project sentinel (disable entirely)


def serve_buttons() -> None:
    """Run the Telegram button callback handler (blocking long-poll loop)."""
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    print(f"[notify-serve] Button server started. Polling for callbacks...")
    print(f"[notify-serve] Press Ctrl+C to stop.\n")

    offset = 0
    while True:
        try:
            result = _telegram_api("getUpdates", {
                "offset": offset,
                "timeout": 30,  # long poll
                "allowed_updates": ["callback_query"],
            }, timeout=35)

            if not result or not result.get("ok"):
                time.sleep(5)
                continue

            for update in result.get("result", []):
                offset = update["update_id"] + 1
                callback = update.get("callback_query")
                if not callback:
                    continue
                _handle_button(callback)

        except KeyboardInterrupt:
            print("\n[notify-serve] Stopped.")
            break
        except Exception as e:
            _log(f"Serve error: {e}")
            time.sleep(5)


def _handle_button(callback: dict) -> None:
    """Handle an inline button press from Telegram."""
    data = callback.get("data", "")
    callback_id = callback.get("id", "")
    user = callback.get("from", {}).get("first_name", "?")

    sender_id = str(callback.get("from", {}).get("id", ""))
    if sender_id != CHAT_ID:
        _answer_callback(callback_id, "Unauthorized")
        _log(f"Rejected button press from {sender_id} (expected {CHAT_ID})")
        return

    if data.startswith("mute_30_"):
        project = data[8:]
        until = time.time() + 1800  # 30 minutes
        _write_state(project, "mute.json", {"until": until})
        _answer_callback(callback_id, f"🔇 {project} muted for 30 minutes")
        print(f"[notify-serve] {user} muted {project} for 30m")

    elif data.startswith("mute_proj_"):
        project = data[10:]
        # Remove project sentinel
        sentinel = SENTINEL_DIR / f"notify-enabled.{project}"
        sentinel.unlink(missing_ok=True)
        _clear_state(project, "mute.json")
        _answer_callback(callback_id, f"🔕 {project} notifications disabled")
        print(f"[notify-serve] {user} disabled {project} notifications")

    else:
        _answer_callback(callback_id, "Unknown action")


def _answer_callback(callback_id: str, text: str) -> None:
    """Acknowledge a callback query (removes loading spinner on button)."""
    _telegram_api("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text,
        "show_alert": False,
    })


# ── Main Entry Point ─────────────────────────────────────────────────────────


def main() -> None:
    """Hook handler: read event from stdin, format, send with all features."""
    # Read hook JSON from stdin (need project name before gate check)
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            _log("Empty stdin, nothing to do")
            return
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        _log(f"Invalid JSON on stdin: {e}")
        return

    project = _extract_project(event)
    event_name = event.get("hook_event_name", "Unknown")

    # ── Gate: enabled + not muted + not suppressed ───────────────────────
    if not _is_enabled(project):
        return
    if event_name in SUPPRESS:
        return
    if MIN_SESSION_AGE > 0:
        age = _session_age_seconds(project)
        if age is not None and age < MIN_SESSION_AGE:
            return

    # ── Flush stale debounce batch (older than window) ───────────────────
    if _debounce_should_flush(project):
        batch_msg = _debounce_flush(project)
        if batch_msg:
            _send_threaded(batch_msg, project)

    # ── Handle debounce-eligible events ──────────────────────────────────
    if event_name in DEBOUNCE_EVENTS:
        _debounce_accumulate(project, event)
        return  # Don't send yet — wait for flush

    # ── Stop event: flush everything, clean up session state ─────────────
    if event_name == "Stop":
        # Flush any pending debounce batch
        batch_msg = _debounce_flush(project)
        if batch_msg:
            _send_threaded(batch_msg, project)

        # Send the Stop message itself
        msg = format_full(event_name, event, project)
        _send_threaded(msg, project)

        # Clean up session state
        _clear_tasks(project)
        _clear_thread(project)
        _clear_state(project, "debounce.json")
        return

    # ── Non-debounce events: flush pending, then send ────────────────────
    # Flush any pending batch first (even if not stale — a real event arrived)
    batch_msg = _debounce_flush(project)
    if batch_msg:
        _send_threaded(batch_msg, project)

    # Format based on event importance
    if event_name in FULL_FORMAT_EVENTS:
        msg = format_full(event_name, event, project)
    else:
        msg = format_compact(event_name, event, project)

    _send_threaded(msg, project)


def _send_threaded(text: str, project: str) -> None:
    """Send a message with thread grouping."""
    reply_to = _get_thread_id(project)
    message_id = send_message(text, project=project, reply_to=reply_to)

    if message_id and reply_to is None:
        # First message in session — store for threading
        _set_thread_id(project, message_id)

    if message_id:
        _log(f"Sent notification (msg_id={message_id})")
    else:
        _log("Failed to send notification")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve_buttons()
    else:
        main()
