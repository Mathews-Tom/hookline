"""Serve daemon: long-poll loop for buttons, replies, approvals, relay."""
from __future__ import annotations

import os
import sys
import time

from hookline._log import log, setup_serve_logging
from hookline.approval import _handle_approval_callback
from hookline.config import (
    BOT_TOKEN,
    CHAT_ID,
    MEMORY_ENABLED,
    RELAY_ENABLED,
    SENTINEL_DIR,
    STATE_DIR,
)
from hookline.state import _clear_state, _write_state
from hookline.tasks import _clear_tasks
from hookline.telegram import _answer_callback, _telegram_api
from hookline.threads import _clear_thread

SERVE_PID_FILE = STATE_DIR / "serve.pid"


def serve() -> None:
    """Run the Telegram update handler (blocking long-poll loop)."""
    if not BOT_TOKEN:
        print("Error: TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    setup_serve_logging(STATE_DIR)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SERVE_PID_FILE.write_text(str(os.getpid()))

    print("[hookline-serve] Daemon started. Polling for updates...")
    print("[hookline-serve] Handles: button callbacks, reply commands, relay")
    print("[hookline-serve] Press Ctrl+C to stop.\n")

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
                        _handle_message(update["message"])

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"Serve error: {e}")
                time.sleep(5)
    except KeyboardInterrupt:
        print("\n[hookline-serve] Stopped.")
    finally:
        SERVE_PID_FILE.unlink(missing_ok=True)


def _handle_message(message: dict) -> None:
    """Route an incoming Telegram message to replies, commands, or relay."""
    sender_id = str(message.get("from", {}).get("id", ""))
    if sender_id != CHAT_ID:
        return

    text = message.get("text", "").strip()
    if not text:
        return

    reply_to = message.get("reply_to_message", {})
    reply_msg_id = reply_to.get("message_id")

    if reply_msg_id:
        # Thread-scoped message: try reply commands first, then relay commands
        _handle_threaded_message(message, text, reply_msg_id)
    elif RELAY_ENABLED:
        # Free-standing message (not a reply): route through relay commands
        _handle_freestanding_message(message, text)


def _handle_threaded_message(message: dict, text: str, reply_msg_id: int) -> None:
    """Handle a message that is a reply to a notification thread."""
    from hookline.commands import dispatch
    from hookline.replies import _handle_reply_message
    from hookline.threads import _find_thread_by_message_id

    thread = _find_thread_by_message_id(reply_msg_id)
    project = thread.get("project", "") if thread else ""
    chat_msg_id: int = message.get("message_id", 0)
    if not chat_msg_id:
        return

    # Parse command and args
    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    # Try new command registry first (relay commands: send, pause, resume, etc.)
    if dispatch(cmd, project, args, chat_msg_id):
        return

    # Fall back to legacy reply handlers (log, full, errors, tools, help)
    _handle_reply_message(message)

    # Log message to memory store
    _log_to_memory(project, "telegram", text)


def _handle_freestanding_message(message: dict, text: str) -> None:
    """Handle a free-standing message (not a reply) through relay commands."""
    from hookline.commands import dispatch

    chat_msg_id: int = message.get("message_id", 0)
    if not chat_msg_id:
        return

    parts = text.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    # Commands that work without a project context
    if cmd in ("sessions", "help"):
        dispatch(cmd, "", args, chat_msg_id)
        return

    # For project-scoped commands, try to infer project from recent sessions
    if dispatch(cmd, "", args, chat_msg_id):
        return

    # Log free-standing message to memory if we can resolve a project
    if MEMORY_ENABLED and RELAY_ENABLED:
        from hookline.relay import list_active_sessions as _list_sessions
        _sessions = _list_sessions()
        if len(_sessions) == 1:
            _log_to_memory(_sessions[0]["project"], "telegram", text)

    # Unrecognised free-standing text: queue to relay if exactly one active session
    if RELAY_ENABLED:
        from hookline.relay import list_active_sessions, write_inbox
        sessions = list_active_sessions()
        if len(sessions) == 1:
            project = sessions[0]["project"]
            write_inbox(project, "telegram", text)
            _telegram_api("sendMessage", {
                "chat_id": CHAT_ID,
                "text": f"Queued to <b>{project}</b>",
                "parse_mode": "HTML",
                "reply_to_message_id": chat_msg_id,
            })
        elif len(sessions) > 1:
            from hookline.formatting import _esc
            names = ", ".join(_esc(s["project"]) for s in sessions)
            _telegram_api("sendMessage", {
                "chat_id": CHAT_ID,
                "text": (
                    f"Multiple sessions active: {names}\n"
                    "Reply to a thread or use <code>send &lt;msg&gt;</code>"
                ),
                "parse_mode": "HTML",
                "reply_to_message_id": chat_msg_id,
            })


def _handle_button(callback: dict) -> None:
    """Handle an inline button press from Telegram."""
    data = callback.get("data", "")
    callback_id = callback.get("id", "")
    user = callback.get("from", {}).get("first_name", "?")

    sender_id = str(callback.get("from", {}).get("id", ""))
    if sender_id != CHAT_ID:
        _answer_callback(callback_id, "Unauthorized")
        log(f"Rejected button press from {sender_id} (expected {CHAT_ID})")
        return

    if data.startswith("mute_30_"):
        project = data[8:]
        until = time.time() + 1800
        _write_state(project, "mute.json", {"until": until})
        _answer_callback(callback_id, f"🔇 {project} muted for 30 minutes")
        print(f"[hookline-serve] {user} muted {project} for 30m")

    elif data.startswith("mute_proj_"):
        project = data[10:]
        sentinel = SENTINEL_DIR / f"notify-enabled.{project}"
        sentinel.unlink(missing_ok=True)
        _clear_state(project, "mute.json")
        _answer_callback(callback_id, f"🔕 {project} notifications disabled")
        print(f"[hookline-serve] {user} disabled {project} notifications")

    elif data.startswith("reset_"):
        project = data[6:]
        _clear_thread(project)
        _clear_tasks(project)
        _clear_state(project, "debounce.json")
        _answer_callback(callback_id, "📌 Thread reset — next message starts fresh")
        print(f"[hookline-serve] {user} reset thread for {project}")

    elif data.startswith("approve_") or data.startswith("block_"):
        _handle_approval_callback(callback)

    else:
        _answer_callback(callback_id, "Unknown action")


def _log_to_memory(project: str, sender: str, text: str) -> None:
    """Log a message to memory store if memory is enabled."""
    if not MEMORY_ENABLED or not project or not text:
        return
    try:
        from hookline.memory.knowledge import KnowledgeManager
        from hookline.memory.store import get_store
        km = KnowledgeManager(get_store())
        km.process_message(project, sender, text)
    except Exception as e:
        log(f"Memory log error: {e}")
