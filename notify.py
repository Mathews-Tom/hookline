#!/usr/bin/env python3
"""
Claude Code Hook → Telegram Notifier (v3)

Bidirectional Telegram interface for Claude Code with:
  - Rich HTML notifications with tool call summaries and error detection
  - Project emoji mapping (~/.claude/notify-projects.json)
  - User preferences via ~/.claude/notify-config.json (env vars override)
  - Session duration tracking (from sentinel timestamp)
  - SubagentStop/TeammateIdle debouncing (batches rapid-fire events)
  - TaskCompleted progress tracking (Task 3/6)
  - Thread grouping (all session messages under one thread)
  - Inline mute buttons (on by default with --serve daemon)
  - On-demand transcript queries via Telegram reply (log, full, errors, tools)
  - Tool approval via Telegram inline buttons (opt-in, PreToolUse hook)

Config precedence: env var → ~/.claude/notify-config.json → hardcoded default
Credentials (BOT_TOKEN, CHAT_ID) always from env vars (secrets stay in environment).

Hook events: Stop, Notification, TeammateIdle, TaskCompleted, SubagentStop, PreToolUse

Usage (called by Claude Code hooks, not manually):
  echo '{"hook_event_name": "Stop", ...}' | python3 notify.py

Serve daemon (for buttons, reply commands, and tool approval):
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
NOTIFY_CONFIG_PATH = CLAUDE_DIR / "notify-config.json"

# Credentials: always from environment (secrets stay as env vars)
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


# ── Config File Loader ──────────────────────────────────────────────────────
# Precedence: env var → config file → hardcoded default

_notify_config: dict | None = None


def _load_config() -> dict[str, Any]:
    """Load ~/.claude/notify-config.json (cached per invocation)."""
    global _notify_config
    if _notify_config is None:
        try:
            _notify_config = json.loads(NOTIFY_CONFIG_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            _notify_config = {}
    return _notify_config  # type: ignore[return-value]


def _cfg_bool(env_key: str, config_key: str, default: bool) -> bool:
    """Read a boolean: env var ("1"/"0") → config file (true/false) → default."""
    env = os.environ.get(env_key)
    if env is not None:
        return env == "1"
    val = _load_config().get(config_key)
    if isinstance(val, bool):
        return val
    return default


def _cfg_int(env_key: str, config_key: str, default: int) -> int:
    """Read an integer: env var → config file → default."""
    env = os.environ.get(env_key)
    if env is not None:
        return int(env)
    val = _load_config().get(config_key)
    if isinstance(val, int):
        return val
    return default


def _cfg_str(env_key: str, config_key: str, default: str) -> str:
    """Read a string: env var → config file → default."""
    env = os.environ.get(env_key)
    if env is not None:
        return env
    val = _load_config().get(config_key)
    if isinstance(val, str):
        return val
    return default


def _cfg_suppress(env_key: str, config_key: str) -> set[str]:
    """Read suppress list: env var (comma-separated) → config file (list) → empty set."""
    env = os.environ.get(env_key)
    if env is not None:
        return set(env.split(",")) - {""}
    val = _load_config().get(config_key)
    if isinstance(val, list):
        return {str(v) for v in val if v}
    return set()


# Preferences: env var → config file → hardcoded default
SUPPRESS = _cfg_suppress("CLAUDE_NOTIFY_SUPPRESS", "suppress")
MIN_SESSION_AGE = _cfg_int("CLAUDE_NOTIFY_MIN_AGE", "min_session_age", 0)
SHOW_BUTTONS = _cfg_bool("CLAUDE_NOTIFY_BUTTONS", "show_buttons", True)
DEBOUNCE_WINDOW = _cfg_int("CLAUDE_NOTIFY_DEBOUNCE", "debounce_window", 30)

# Tool approval settings
APPROVAL_ENABLED = _cfg_bool("CLAUDE_NOTIFY_APPROVAL", "approval_enabled", False)
APPROVAL_USER = _cfg_str("CLAUDE_NOTIFY_APPROVAL_USER", "approval_user", "") or CHAT_ID
APPROVAL_TIMEOUT = _cfg_int("CLAUDE_NOTIFY_APPROVAL_TIMEOUT", "approval_timeout", 120)

# Audit log path
AUDIT_LOG = STATE_DIR / "audit.jsonl"

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


def _find_thread_by_message_id(message_id: int) -> dict | None:
    """Look up thread state across all projects by message_id. Returns thread dict or None."""
    if not STATE_DIR.exists():
        return None
    for project_dir in STATE_DIR.iterdir():
        if not project_dir.is_dir():
            continue
        thread_file = project_dir / "thread.json"
        if not thread_file.exists():
            continue
        try:
            state = json.loads(thread_file.read_text())
            if state.get("message_id") == message_id:
                state["project"] = project_dir.name
                return state
        except (OSError, json.JSONDecodeError):
            continue
    return None


def _set_thread_id(project: str, message_id: int, transcript_path: str = "") -> None:
    """Store the first message_id for thread grouping, with optional transcript path."""
    data: dict[str, Any] = {
        "session": _session_key(project),
        "message_id": message_id,
    }
    if transcript_path:
        data["transcript_path"] = transcript_path
    _write_state(project, "thread.json", data)


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


def _read_transcript_tail(transcript_path: str, tail_bytes: int = 32768) -> list[dict]:
    """Read and parse the last N bytes of a JSONL transcript. Returns list of parsed entries."""
    if not transcript_path:
        return []
    path = Path(transcript_path)
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        if size > 10 * 1024 * 1024:  # 10MB
            _log(f"Transcript too large ({size} bytes), skipping extraction")
            return []
        read_size = min(size, tail_bytes)
        with path.open("rb") as f:
            if size > read_size:
                f.seek(-read_size, 2)
            raw = f.read().decode("utf-8", errors="replace")
        lines = raw.split("\n")
        if size > read_size:
            lines = lines[1:]  # discard partial first line from seek
        entries: list[dict] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                entries.append(json.loads(line))
            except (json.JSONDecodeError, AttributeError):
                continue
        return entries
    except (OSError, PermissionError):
        return []


def _extract_transcript_summary(event: dict) -> dict[str, Any]:
    """Extract structured summary from transcript tail.

    Returns dict with:
        messages: list[str]  — last N assistant text blocks (newest first)
        tool_summary: str    — e.g. "12 tool calls: 5 Bash, 4 Read, 3 Edit"
        errors: list[str]    — error messages from tool results
    """
    entries = _read_transcript_tail(event.get("transcript_path", ""))
    if not entries:
        return {"messages": [], "tool_summary": "", "errors": []}

    messages: list[str] = []
    tool_counts: dict[str, int] = {}
    errors: list[str] = []

    for entry in reversed(entries):
        msg = entry.get("message", {})
        role = msg.get("role", "")
        content = msg.get("content", [])

        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue

            # Collect assistant text blocks (up to 3)
            if role == "assistant" and block.get("type") == "text" and len(messages) < 3:
                text = block.get("text", "").strip()
                if text:
                    messages.append(text)

            # Count tool_use blocks
            if role == "assistant" and block.get("type") == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

            # Detect errors in tool_result blocks
            if role == "user" and block.get("type") == "tool_result":
                if block.get("is_error"):
                    err_content = block.get("content", "")
                    if isinstance(err_content, str) and err_content.strip():
                        errors.append(err_content.strip()[:200])
                    elif isinstance(err_content, list):
                        for sub in err_content:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                errors.append(sub.get("text", "").strip()[:200])

    # Build tool summary string
    tool_summary = ""
    if tool_counts:
        total = sum(tool_counts.values())
        sorted_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
        top = ", ".join(f"{c} {n}" for n, c in sorted_tools[:5])
        tool_summary = f"{total} tool calls: {top}"

    return {
        "messages": messages,
        "tool_summary": tool_summary,
        "errors": errors[:3],  # cap at 3 errors
    }


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
            summary = _extract_transcript_summary(event)
            stop_active = event.get("stop_hook_active", False)
            lines: list[str] = []

            # Last assistant messages (newest first, show up to 3)
            msgs = summary.get("messages", [])
            if msgs:
                lines.append(_esc(_truncate(msgs[0], 250)))
                for extra in msgs[1:]:
                    lines.append(f"<i>{_esc(_truncate(extra, 150))}</i>")

            # Tool call summary
            tool_sum = summary.get("tool_summary", "")
            if tool_sum:
                lines.append(f"🔧 {_esc(tool_sum)}")

            # Errors from transcript
            errs = summary.get("errors", [])
            if errs:
                for err in errs:
                    lines.append(f"❗ {_esc(_truncate(err, 150))}")

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

    # Inline buttons (only if button server is enabled)
    if SHOW_BUTTONS and project:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [
                    {"text": "🔇 Mute 30m", "callback_data": f"mute_30_{project}"},
                    {"text": "🔇 Mute Project", "callback_data": f"mute_proj_{project}"},
                ],
                [
                    {"text": "📌 New Thread", "callback_data": f"reset_{project}"},
                ],
            ]
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


# ── Serve Daemon ─────────────────────────────────────────────────────────────
# Optional companion mode: `python3 notify.py --serve`
# Long-polls Telegram for:
#   - Inline button callbacks (mute controls, approval responses)
#   - Text message replies (transcript queries: log, full, errors, tools)

SERVE_PID_FILE = STATE_DIR / "serve.pid"

REPLY_COMMANDS: dict[str, str] = {
    "log": "Last 3 assistant messages with tool summary",
    "details": "Last 3 assistant messages with tool summary",
    "full": "Upload transcript tail as .txt document",
    "errors": "Extract and send only error blocks",
    "tools": "List all tool calls made in the session",
    "help": "Show available commands",
}


def serve() -> None:
    """Run the Telegram update handler (blocking long-poll loop).

    Handles inline button callbacks AND text message replies to notification threads.
    """
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    # Write PID file for daemon detection
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SERVE_PID_FILE.write_text(str(os.getpid()))

    print("[notify-serve] Daemon started. Polling for updates...")
    print("[notify-serve] Handles: button callbacks, reply commands")
    print("[notify-serve] Press Ctrl+C to stop.\n")

    offset = 0
    try:
        while True:
            try:
                result = _telegram_api("getUpdates", {
                    "offset": offset,
                    "timeout": 30,
                    "allowed_updates": ["callback_query", "message"],
                }, timeout=35)

                if not result or not result.get("ok"):
                    time.sleep(5)
                    continue

                for update in result.get("result", []):
                    offset = update["update_id"] + 1

                    if "callback_query" in update:
                        _handle_button(update["callback_query"])
                    elif "message" in update:
                        _handle_reply_message(update["message"])

            except KeyboardInterrupt:
                raise
            except Exception as e:
                _log(f"Serve error: {e}")
                time.sleep(5)
    except KeyboardInterrupt:
        print("\n[notify-serve] Stopped.")
    finally:
        SERVE_PID_FILE.unlink(missing_ok=True)


def _is_serve_running() -> bool:
    """Check if the serve daemon is running by verifying its PID file."""
    if not SERVE_PID_FILE.exists():
        return False
    try:
        pid = int(SERVE_PID_FILE.read_text().strip())
        os.kill(pid, 0)  # signal 0 = check if process exists
        return True
    except (OSError, ValueError):
        SERVE_PID_FILE.unlink(missing_ok=True)
        return False


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

    elif data.startswith("reset_"):
        project = data[6:]
        _clear_thread(project)
        _clear_tasks(project)
        _clear_state(project, "debounce.json")
        _answer_callback(callback_id, f"📌 Thread reset — next message starts fresh")
        print(f"[notify-serve] {user} reset thread for {project}")

    elif data.startswith("approve_") or data.startswith("block_"):
        _handle_approval_callback(callback)

    else:
        _answer_callback(callback_id, "Unknown action")


def _answer_callback(callback_id: str, text: str) -> None:
    """Acknowledge a callback query (removes loading spinner on button)."""
    _telegram_api("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text,
        "show_alert": False,
    })


# ── Reply Message Handlers ──────────────────────────────────────────────────


def _handle_reply_message(message: dict) -> None:
    """Handle a text message reply to a notification thread."""
    reply_to = message.get("reply_to_message", {})
    reply_msg_id = reply_to.get("message_id")
    if not reply_msg_id:
        return

    sender_id = str(message.get("from", {}).get("id", ""))
    if sender_id != CHAT_ID:
        return

    text = message.get("text", "").strip().lower()
    if not text:
        return

    # Resolve the reply target to a thread state
    thread = _find_thread_by_message_id(reply_msg_id)
    if not thread:
        _telegram_api("sendMessage", {
            "chat_id": CHAT_ID,
            "text": "No session found for this thread.",
            "reply_to_message_id": message.get("message_id"),
        })
        return

    transcript_path = thread.get("transcript_path", "")
    project = thread.get("project", "unknown")
    chat_msg_id: int = message.get("message_id", 0)
    if not chat_msg_id:
        return

    cmd = text.split()[0]
    if cmd in ("log", "details"):
        _cmd_log(transcript_path, project, chat_msg_id)
    elif cmd == "full":
        _cmd_full(transcript_path, project, chat_msg_id)
    elif cmd == "errors":
        _cmd_errors(transcript_path, project, chat_msg_id)
    elif cmd == "tools":
        _cmd_tools(transcript_path, project, chat_msg_id)
    else:
        _cmd_help(chat_msg_id)


def _cmd_log(transcript_path: str, project: str, reply_to: int) -> None:
    """Send last 3 assistant messages with tool summary."""
    entries = _read_transcript_tail(transcript_path)
    if not entries:
        _telegram_api("sendMessage", {
            "chat_id": CHAT_ID,
            "text": "Transcript not found or empty.",
            "reply_to_message_id": reply_to,
        })
        return

    summary = _extract_transcript_summary({"transcript_path": transcript_path})
    label = _project_label(project)
    lines: list[str] = [f"<b>📋 Transcript — {_esc(label)}</b>", ""]

    msgs = summary.get("messages", [])
    if msgs:
        for i, msg in enumerate(msgs):
            prefix = "→" if i == 0 else "·"
            lines.append(f"{prefix} {_esc(_truncate(msg, 300))}")
        lines.append("")

    tool_sum = summary.get("tool_summary", "")
    if tool_sum:
        lines.append(f"🔧 {_esc(tool_sum)}")

    errs = summary.get("errors", [])
    if errs:
        lines.append("")
        for err in errs:
            lines.append(f"❗ {_esc(_truncate(err, 200))}")

    if len(lines) <= 2:
        lines.append("No assistant messages found in transcript tail.")

    _telegram_api("sendMessage", {
        "chat_id": CHAT_ID,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "reply_to_message_id": reply_to,
    })


def _cmd_full(transcript_path: str, project: str, reply_to: int) -> None:
    """Upload transcript tail as a .txt document."""
    entries = _read_transcript_tail(transcript_path, tail_bytes=65536)
    if not entries:
        _telegram_api("sendMessage", {
            "chat_id": CHAT_ID,
            "text": "Transcript not found or empty.",
            "reply_to_message_id": reply_to,
        })
        return

    text_lines: list[str] = []
    for entry in entries:
        msg = entry.get("message", {})
        role = msg.get("role", "")
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                text_lines.append(f"[{role}] {block.get('text', '')}")
            elif block.get("type") == "tool_use":
                text_lines.append(
                    f"[{role}:tool_use] {block.get('name', '')}"
                    f"({json.dumps(block.get('input', {}))[:200]})"
                )
            elif block.get("type") == "tool_result":
                snippet = str(block.get("content", ""))[:300]
                is_err = " ERROR" if block.get("is_error") else ""
                text_lines.append(f"[{role}:tool_result{is_err}] {snippet}")

    content_text = "\n\n".join(text_lines)
    if not content_text:
        content_text = "No parseable content in transcript tail."

    _send_document(
        content_text.encode("utf-8"),
        filename=f"transcript_{project}.txt",
        caption=f"Transcript tail — {project}",
        reply_to=reply_to,
    )


def _cmd_errors(transcript_path: str, project: str, reply_to: int) -> None:
    """Extract and send only error blocks from transcript."""
    entries = _read_transcript_tail(transcript_path)
    if not entries:
        _telegram_api("sendMessage", {
            "chat_id": CHAT_ID,
            "text": "Transcript not found or empty.",
            "reply_to_message_id": reply_to,
        })
        return

    errors: list[str] = []
    for entry in entries:
        msg = entry.get("message", {})
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result" and block.get("is_error"):
                err_content = block.get("content", "")
                if isinstance(err_content, str) and err_content.strip():
                    errors.append(err_content.strip()[:300])
                elif isinstance(err_content, list):
                    for sub in err_content:
                        if isinstance(sub, dict) and sub.get("type") == "text":
                            errors.append(sub.get("text", "").strip()[:300])

    label = _project_label(project)
    if errors:
        lines = [f"<b>❗ Errors — {_esc(label)}</b>", ""]
        for i, err in enumerate(errors[-10:], 1):
            lines.append(f"{i}. <code>{_esc(_truncate(err, 250))}</code>")
        text = "\n".join(lines)
    else:
        text = f"No errors found in transcript — {_esc(label)}"

    _telegram_api("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_to_message_id": reply_to,
    })


def _cmd_tools(transcript_path: str, project: str, reply_to: int) -> None:
    """List all tool calls made in the session."""
    entries = _read_transcript_tail(transcript_path, tail_bytes=65536)
    if not entries:
        _telegram_api("sendMessage", {
            "chat_id": CHAT_ID,
            "text": "Transcript not found or empty.",
            "reply_to_message_id": reply_to,
        })
        return

    tool_counts: dict[str, int] = {}
    for entry in entries:
        msg = entry.get("message", {})
        if msg.get("role") != "assistant":
            continue
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "unknown")
                tool_counts[name] = tool_counts.get(name, 0) + 1

    label = _project_label(project)
    if tool_counts:
        total = sum(tool_counts.values())
        sorted_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
        lines = [f"<b>🔧 Tool Calls — {_esc(label)}</b> ({total} total)", ""]
        for name, count in sorted_tools:
            bar = "█" * min(count, 20)
            lines.append(f"  <code>{_esc(name):20s}</code> {bar} {count}")
        text = "\n".join(lines)
    else:
        text = f"No tool calls found in transcript — {_esc(label)}"

    _telegram_api("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "reply_to_message_id": reply_to,
    })


def _cmd_help(reply_to: int) -> None:
    """Send list of available reply commands."""
    lines = ["<b>Reply commands:</b>", ""]
    for cmd, desc in REPLY_COMMANDS.items():
        lines.append(f"  <b>{cmd}</b> — {desc}")
    _telegram_api("sendMessage", {
        "chat_id": CHAT_ID,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "reply_to_message_id": reply_to,
    })


def _send_document(
    file_bytes: bytes,
    filename: str,
    caption: str = "",
    reply_to: int | None = None,
) -> None:
    """Send a file as a Telegram document using multipart/form-data."""
    import uuid
    boundary = uuid.uuid4().hex
    body_parts: list[bytes] = []

    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{CHAT_ID}".encode()
    )
    if caption:
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}".encode()
        )
    if reply_to:
        body_parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"reply_to_message_id\"\r\n\r\n{reply_to}".encode()
        )

    body_parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{filename}\"\r\n"
        f"Content-Type: text/plain\r\n\r\n".encode() + file_bytes
    )
    body_parts.append(f"--{boundary}--".encode())
    body = b"\r\n".join(body_parts)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                _log(f"sendDocument failed: {result}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        _log(f"sendDocument error: {e}")


# ── Tool Approval (Phase 3) ─────────────────────────────────────────────────
# PreToolUse hook: sends approval request to Telegram, blocks on named pipe.
# The --serve daemon writes the decision to the pipe when the user taps a button.


def _approval_pipe_path(approval_id: str) -> Path:
    """Get the named pipe path for an approval request."""
    pipe_dir = STATE_DIR / "_approvals"
    pipe_dir.mkdir(parents=True, exist_ok=True)
    return pipe_dir / f"approval_{approval_id}"


def _audit_log_entry(entry: dict) -> None:
    """Append an entry to the approval audit log."""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        _log(f"Audit log write error: {e}")


def _format_approval_message(event: dict, project: str) -> str:
    """Format the approval request message for Telegram."""
    tool_name = event.get("tool_name", "unknown")
    tool_input = event.get("tool_input", {})
    label = _project_label(project)
    duration = _session_duration(project)

    # Extract relevant input preview
    input_preview = ""
    if tool_name == "Bash" and isinstance(tool_input, dict):
        input_preview = tool_input.get("command", "")[:200]
    elif tool_name == "Write" and isinstance(tool_input, dict):
        input_preview = tool_input.get("file_path", "")
    elif tool_name == "Edit" and isinstance(tool_input, dict):
        input_preview = tool_input.get("file_path", "")
    elif isinstance(tool_input, dict):
        # Generic: show first string value
        for v in tool_input.values():
            if isinstance(v, str) and v.strip():
                input_preview = v[:200]
                break

    lines = [
        f"<b>┌─ 🔐 Approval Required ─────── {_esc(label)}</b>",
        f"│ Tool: <b>{_esc(tool_name)}</b>",
    ]
    if input_preview:
        lines.append(f"│ <code>{_esc(_truncate(input_preview, 200))}</code>")
    if duration:
        lines.append(f"│ Session: {duration} active")
    lines.append(f"<i>└─ ⏳ Waiting ({APPROVAL_TIMEOUT}s timeout)</i>")

    return "\n".join(lines)


def _format_approval_result(event: dict, project: str, decision: str, user: str = "") -> str:
    """Format the edited message after approval decision."""
    tool_name = event.get("tool_name", "unknown")
    label = _project_label(project)
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")

    if decision == "approve":
        emoji = "✅"
        status = "Approved"
    elif decision == "block":
        emoji = "❌"
        status = "Blocked"
    else:
        emoji = "⏰"
        status = "Timed out (auto-blocked)"

    tool_input = event.get("tool_input", {})
    input_preview = ""
    if tool_name == "Bash" and isinstance(tool_input, dict):
        input_preview = tool_input.get("command", "")[:200]
    elif isinstance(tool_input, dict):
        for v in tool_input.values():
            if isinstance(v, str) and v.strip():
                input_preview = v[:200]
                break

    lines = [
        f"<b>┌─ {emoji} {status} ─────── {_esc(label)}</b>",
        f"│ Tool: <b>{_esc(tool_name)}</b>",
    ]
    if input_preview:
        lines.append(f"│ <code>{_esc(_truncate(input_preview, 200))}</code>")

    by_str = f"by {_esc(user)} · " if user else ""
    lines.append(f"<i>└─ {status} {by_str}{ts}</i>")

    return "\n".join(lines)


def _handle_pre_tool_use(event: dict) -> None:
    """Handle PreToolUse hook: send approval request, block on pipe, output decision.

    Outputs JSON to stdout for Claude Code to consume:
      {"decision": "approve"} or {"decision": "block", "reason": "..."}
    """
    import select
    import uuid

    project = _extract_project(event)
    tool_name = event.get("tool_name", "unknown")

    # Gate: approval must be opt-in
    if not APPROVAL_ENABLED:
        return  # passthrough — no output means Claude Code continues normally

    # Gate: daemon must be running
    if not _is_serve_running():
        _log("Serve daemon not running — skipping approval, auto-blocking")
        # Send notification that approval was needed but daemon was down
        if _is_enabled(project):
            label = _project_label(project)
            msg = (
                f"<b>⚠️ Approval needed but daemon offline</b>\n"
                f"Tool: <b>{_esc(tool_name)}</b> · {_esc(label)}\n"
                f"<i>Auto-blocked. Start daemon: python3 ~/.claude/hooks/notify.py --serve</i>"
            )
            _send_threaded(msg, project)

        _output_decision("block", "Serve daemon not running")
        return

    approval_id = uuid.uuid4().hex[:12]
    pipe_path = _approval_pipe_path(approval_id)

    # Create named pipe
    try:
        os.mkfifo(pipe_path)
    except OSError as e:
        _log(f"Failed to create approval pipe: {e}")
        _output_decision("block", f"Internal error: {e}")
        return

    try:
        # Send approval message to Telegram
        text = _format_approval_message(event, project)
        keyboard = {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve_{approval_id}"},
                {"text": "❌ Block", "callback_data": f"block_{approval_id}"},
            ]]
        }
        payload: dict[str, Any] = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": keyboard,
        }
        reply_to = _get_thread_id(project)
        if reply_to:
            payload["reply_to_message_id"] = reply_to
            payload["allow_sending_without_reply"] = True

        result = _telegram_api("sendMessage", payload)
        msg_id = result["result"]["message_id"] if result and result.get("ok") else None

        if not msg_id:
            _log("Failed to send approval message")
            _output_decision("block", "Failed to send approval request")
            return

        # Store approval metadata for the serve daemon to resolve
        _write_state("_approvals", f"{approval_id}.json", {
            "approval_id": approval_id,
            "message_id": msg_id,
            "project": project,
            "tool_name": tool_name,
            "tool_input": event.get("tool_input", {}),
            "pipe_path": str(pipe_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "event": {k: v for k, v in event.items() if k != "transcript_path"},  # exclude large fields
        })

        # Block reading from pipe with timeout
        _log(f"Waiting for approval decision (id={approval_id}, timeout={APPROVAL_TIMEOUT}s)")
        fd = os.open(str(pipe_path), os.O_RDONLY | os.O_NONBLOCK)
        try:
            ready, _, _ = select.select([fd], [], [], APPROVAL_TIMEOUT)
            if ready:
                decision_raw = os.read(fd, 1024).decode("utf-8").strip()
            else:
                decision_raw = ""
        finally:
            os.close(fd)

        # Parse decision
        if decision_raw in ("approve", "block"):
            decision = decision_raw
        else:
            decision = "block"  # timeout or invalid → auto-block

        reason = "Timed out" if not decision_raw else ""
        user_name = ""

        # Read approval metadata for user info
        approval_state = _read_state("_approvals", f"{approval_id}.json")
        if approval_state.get("decided_by"):
            user_name = approval_state["decided_by"]
        if approval_state.get("reason"):
            reason = approval_state["reason"]

        # Edit the Telegram message to show result
        if msg_id:
            result_text = _format_approval_result(event, project, decision, user_name)
            _telegram_api("editMessageText", {
                "chat_id": CHAT_ID,
                "message_id": msg_id,
                "text": result_text,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": []},  # remove buttons
            })

        # Audit log
        _audit_log_entry({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "approval_id": approval_id,
            "project": project,
            "tool_name": tool_name,
            "decision": decision,
            "decided_by": user_name,
            "reason": reason,
        })

        # Output decision to Claude Code
        _output_decision(decision, reason)

    finally:
        # Clean up pipe and state
        pipe_path.unlink(missing_ok=True)
        _clear_state("_approvals", f"{approval_id}.json")


def _output_decision(decision: str, reason: str = "") -> None:
    """Output a hook decision as JSON to stdout for Claude Code."""
    output: dict[str, str] = {"decision": decision}
    if reason:
        output["reason"] = reason
    print(json.dumps(output))


def _handle_approval_callback(callback: dict) -> None:
    """Handle an approval button press from the serve daemon."""
    data = callback.get("data", "")
    callback_id = callback.get("id", "")
    sender_id = str(callback.get("from", {}).get("id", ""))
    user_name = callback.get("from", {}).get("first_name", "unknown")

    # Verify sender is the authorized approval user
    if sender_id != APPROVAL_USER:
        _answer_callback(callback_id, "Not authorized for approvals")
        _log(f"Rejected approval from {sender_id} (expected {APPROVAL_USER})")
        return

    # Parse: approve_{id} or block_{id}
    if data.startswith("approve_"):
        approval_id = data[8:]
        decision = "approve"
    elif data.startswith("block_"):
        approval_id = data[6:]
        decision = "block"
    else:
        _answer_callback(callback_id, "Unknown action")
        return

    # Find the approval state
    state = _read_state("_approvals", f"{approval_id}.json")
    if not state:
        _answer_callback(callback_id, "Approval expired or already handled")
        return

    pipe_path = state.get("pipe_path", "")
    if not pipe_path or not Path(pipe_path).exists():
        _answer_callback(callback_id, "Approval expired (pipe gone)")
        return

    # Update state with decision metadata
    state["decided_by"] = user_name
    state["decision"] = decision
    _write_state("_approvals", f"{approval_id}.json", state)

    # Write decision to the named pipe (unblocks the hook process)
    try:
        fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, decision.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        _log(f"Failed to write to approval pipe: {e}")
        _answer_callback(callback_id, f"Error: {e}")
        return

    emoji = "✅" if decision == "approve" else "❌"
    _answer_callback(callback_id, f"{emoji} {decision.title()}d")
    print(f"[notify-serve] {user_name} {decision}d {state.get('tool_name', '?')} (id={approval_id})")


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
    transcript_path = event.get("transcript_path", "")

    # ── PreToolUse: approval flow (has its own gating) ────────────────────
    if event_name == "PreToolUse":
        _handle_pre_tool_use(event)
        return

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
            _send_threaded(batch_msg, project, transcript_path)

    # ── Handle debounce-eligible events ──────────────────────────────────
    if event_name in DEBOUNCE_EVENTS:
        _debounce_accumulate(project, event)
        return  # Don't send yet — wait for flush

    # ── Stop event: flush everything, clean up session state ─────────────
    if event_name == "Stop":
        # Flush any pending debounce batch
        batch_msg = _debounce_flush(project)
        if batch_msg:
            _send_threaded(batch_msg, project, transcript_path)

        # Send the Stop message itself
        msg = format_full(event_name, event, project)
        _send_threaded(msg, project, transcript_path)

        # Clean up session state
        _clear_tasks(project)
        _clear_thread(project)
        _clear_state(project, "debounce.json")
        return

    # ── Non-debounce events: flush pending, then send ────────────────────
    # Flush any pending batch first (even if not stale — a real event arrived)
    batch_msg = _debounce_flush(project)
    if batch_msg:
        _send_threaded(batch_msg, project, transcript_path)

    # Format based on event importance
    if event_name in FULL_FORMAT_EVENTS:
        msg = format_full(event_name, event, project)
    else:
        msg = format_compact(event_name, event, project)

    _send_threaded(msg, project, transcript_path)


def _send_threaded(text: str, project: str, transcript_path: str = "") -> None:
    """Send a message with thread grouping."""
    reply_to = _get_thread_id(project)
    message_id = send_message(text, project=project, reply_to=reply_to)

    if message_id and reply_to is None:
        # First message in session — store for threading
        _set_thread_id(project, message_id, transcript_path=transcript_path)

    if message_id:
        _log(f"Sent notification (msg_id={message_id})")
    else:
        _log("Failed to send notification")


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        main()
