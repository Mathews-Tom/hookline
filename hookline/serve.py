"""Serve daemon: long-poll loop for buttons, replies, approvals."""
from __future__ import annotations

import os
import sys
import time

from hookline._log import log, setup_serve_logging
from hookline.approval import _handle_approval_callback
from hookline.config import BOT_TOKEN, CHAT_ID, SENTINEL_DIR, STATE_DIR
from hookline.replies import _handle_reply_message
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
    print("[hookline-serve] Handles: button callbacks, reply commands")
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
                        _handle_reply_message(update["message"])

            except KeyboardInterrupt:
                raise
            except Exception as e:
                log(f"Serve error: {e}")
                time.sleep(5)
    except KeyboardInterrupt:
        print("\n[hookline-serve] Stopped.")
    finally:
        SERVE_PID_FILE.unlink(missing_ok=True)


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
        _answer_callback(callback_id, f"📌 Thread reset — next message starts fresh")
        print(f"[hookline-serve] {user} reset thread for {project}")

    elif data.startswith("approve_") or data.startswith("block_"):
        _handle_approval_callback(callback)

    else:
        _answer_callback(callback_id, "Unknown action")
