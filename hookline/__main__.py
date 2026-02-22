"""CLI dispatch for python3 -m hookline."""
from __future__ import annotations

import json
import sys

from hookline import __version__
from hookline._log import log
from hookline.approval import _handle_pre_tool_use, _send_threaded
from hookline.buttons import _clear_last_button_msg
from hookline.config import (
    DEBOUNCE_EVENTS,
    DRY_RUN,
    FULL_FORMAT_EVENTS,
    MEMORY_ENABLED,
    MIN_SESSION_AGE,
    RELAY_ENABLED,
    STATE_DIR,
    SUPPRESS,
)
from hookline.debounce import _debounce_accumulate, _debounce_flush, _debounce_should_flush
from hookline.formatting import format_compact, format_full
from hookline.session import _extract_project, _is_enabled, _session_age_seconds
from hookline.state import _clear_state, _is_serve_running
from hookline.tasks import _clear_tasks
from hookline.telegram import _telegram_api
from hookline.threads import _clear_thread


def main() -> None:
    """Hook handler: read event from stdin, format, send with all features."""
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            log("Empty stdin, nothing to do")
            return
        event = json.loads(raw)
    except json.JSONDecodeError as e:
        log(f"Invalid JSON on stdin: {e}")
        return

    project = _extract_project(event)
    event_name = event.get("hook_event_name", "Unknown")
    transcript_path = event.get("transcript_path", "")

    if event_name == "PreToolUse":
        _handle_pre_tool_use(event)
        return

    if not DRY_RUN and not _is_enabled(project):
        return
    if event_name in SUPPRESS:
        return
    if MIN_SESSION_AGE > 0:
        age = _session_age_seconds(project)
        if age is not None and age < MIN_SESSION_AGE:
            return

    if _debounce_should_flush(project):
        batch_msg = _debounce_flush(project)
        if batch_msg:
            _send_threaded(batch_msg, project, transcript_path)

    if event_name in DEBOUNCE_EVENTS:
        _debounce_accumulate(project, event)
        return

    if event_name == "Stop":
        batch_msg = _debounce_flush(project)
        if batch_msg:
            _send_threaded(batch_msg, project, transcript_path)

        msg = format_full(event_name, event, project)
        _send_threaded(msg, project, transcript_path, is_final=True)

        _clear_tasks(project)
        _clear_thread(project)
        _clear_last_button_msg(project)
        _clear_state(project, "debounce.json")
        if RELAY_ENABLED:
            from hookline.relay import clear_inbox, set_paused
            clear_inbox(project)
            set_paused(project, paused=False)
        _log_event_to_memory(project, "stop", "Session ended")
        return

    batch_msg = _debounce_flush(project)
    if batch_msg:
        _send_threaded(batch_msg, project, transcript_path)

    if event_name in FULL_FORMAT_EVENTS:
        msg = format_full(event_name, event, project)
    else:
        msg = format_compact(event_name, event, project)

    _send_threaded(msg, project, transcript_path)

    # Surface unread inbox messages as a digest appended to the notification
    _surface_inbox(project, transcript_path)


def _surface_inbox(project: str, transcript_path: str) -> None:
    """Send unread inbox messages as a digest notification."""
    if not RELAY_ENABLED or not project:
        return
    from hookline.formatting import _esc, _truncate
    from hookline.relay import mark_read, read_inbox

    messages = read_inbox(project, unread_only=True)
    if not messages:
        return

    lines = [f"<b>📨 {len(messages)} message(s) from Telegram</b>", ""]
    msg_ids: list[str] = []
    for msg in messages[-5:]:
        sender = msg.get("sender", "?")
        text = _truncate(msg.get("text", ""), 200)
        lines.append(f"  [{sender}] {_esc(text)}")
        msg_ids.append(msg.get("id", ""))
    if len(messages) > 5:
        lines.append(f"  <i>… and {len(messages) - 5} more</i>")

    _send_threaded("\n".join(lines), project, transcript_path)
    mark_read(project, msg_ids if msg_ids else None)


def health_check() -> None:
    """Run self-diagnostics and print results."""
    from hookline.config import BOT_TOKEN, CHAT_ID

    checks: list[tuple[str, bool, str]] = []

    has_token = bool(BOT_TOKEN)
    checks.append(("BOT_TOKEN", has_token, BOT_TOKEN[:8] + "***" if has_token else "not set"))

    has_chat = bool(CHAT_ID)
    checks.append(("CHAT_ID", has_chat, CHAT_ID if has_chat else "not set"))

    bot_valid = False
    bot_info = ""
    if has_token:
        result = _telegram_api("getMe", {})
        if result and result.get("ok"):
            bot_valid = True
            bot_info = result["result"].get("username", "?")
        else:
            bot_info = "API call failed"
    checks.append(("Bot valid", bot_valid, f"@{bot_info}" if bot_valid else bot_info))

    chat_ok = False
    if has_token and has_chat:
        result = _telegram_api("sendChatAction", {"chat_id": CHAT_ID, "action": "typing"})
        chat_ok = bool(result and result.get("ok"))
    checks.append(("Chat reachable", chat_ok, "OK" if chat_ok else "unreachable"))

    state_ok = False
    state_err = ""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        test_file = STATE_DIR / ".health_check"
        test_file.write_text("ok")
        test_file.unlink()
        state_ok = True
    except OSError as e:
        state_err = str(e)
    checks.append(("State dir", state_ok, str(STATE_DIR) if state_ok else state_err))

    corrupt_files: list[str] = []
    if STATE_DIR.exists():
        for project_dir in STATE_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            for json_file in project_dir.glob("*.json"):
                try:
                    json.loads(json_file.read_text())
                except (json.JSONDecodeError, OSError):
                    corrupt_files.append(str(json_file.relative_to(STATE_DIR)))
    state_clean = len(corrupt_files) == 0
    checks.append(("State files", state_clean,
                    "all valid" if state_clean else f"corrupt: {', '.join(corrupt_files[:3])}"))

    daemon_running = _is_serve_running()
    daemon_info = ""
    if daemon_running:
        from hookline.config import SERVE_PID_FILE
        try:
            pid = SERVE_PID_FILE.read_text().strip()
            daemon_info = f"PID {pid}"
        except OSError:
            daemon_info = "running"
    daemon_detail = daemon_info if daemon_running else "not running"
    checks.append(("Serve daemon", daemon_running, daemon_detail))

    print(f"🩺 hookline v{__version__} health check")
    print("──────────────────────────────────────────────")
    all_ok = True
    for name, ok, detail in checks:
        icon = "✅" if ok else "❌"
        print(f"  {icon} {name:16s} {detail}")
        if not ok:
            all_ok = False
    print("──────────────────────────────────────────────")
    if all_ok:
        print("  ✅ All checks passed")
    else:
        print("  ❌ Issues detected")
    sys.exit(0 if all_ok else 1)


def _log_event_to_memory(project: str, event_type: str, text: str) -> None:
    """Log a hook event to memory store if memory is enabled."""
    if not MEMORY_ENABLED or not project:
        return
    try:
        from hookline.memory.store import get_store
        store = get_store()
        store.log_message(project, "hookline", f"[{event_type}] {text}")
    except Exception as e:
        log(f"Memory event log error: {e}")


if __name__ == "__main__":
    from hookline.cli import cli_main
    cli_main()
