"""Telegram Bot API transport: send messages, documents, remove buttons."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any

from hookline._log import log
from hookline.buttons import _build_buttons, _clear_last_button_msg, _get_last_button_msg, _set_last_button_msg
from hookline.config import BOT_TOKEN, CHAT_ID, DRY_RUN, SHOW_BUTTONS
from hookline.formatting import _strip_html


def _telegram_api(method: str, payload: dict, timeout: int = 10) -> dict | None:
    """Call a Telegram Bot API method. Returns parsed JSON or None."""
    if not BOT_TOKEN:
        log("TELEGRAM_BOT_TOKEN not set")
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
        log(f"Telegram API [{method}]: {e}")
        return None


def _remove_buttons(message_id: int) -> None:
    """Remove inline buttons from a previously sent message."""
    _telegram_api("editMessageReplyMarkup", {
        "chat_id": CHAT_ID,
        "message_id": message_id,
        "reply_markup": {"inline_keyboard": []},
    })


def send_message(
    text: str,
    project: str = "",
    reply_to: int | None = None,
    is_final: bool = False,
) -> int | None:
    """Send an HTML message. Returns message_id on success, None on failure."""
    if DRY_RUN:
        print(f"[dry-run] send_message(project={project!r}, reply_to={reply_to}, is_final={is_final})")
        print(text)
        return 99999

    if not BOT_TOKEN or not CHAT_ID:
        log("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set")
        return None

    if SHOW_BUTTONS and project:
        prev_msg = _get_last_button_msg(project)
        if prev_msg:
            _remove_buttons(prev_msg)

    payload: dict[str, Any] = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    if reply_to:
        payload["reply_to_message_id"] = reply_to
        payload["allow_sending_without_reply"] = True

    if SHOW_BUTTONS and project:
        payload["reply_markup"] = _build_buttons(project, is_final)

    result = _telegram_api("sendMessage", payload)
    if result and result.get("ok"):
        msg_id = result["result"]["message_id"]
        if SHOW_BUTTONS and project:
            _set_last_button_msg(project, msg_id)
        return msg_id

    # Fallback: strip HTML and send plain text
    log("HTML send failed, trying plain text fallback")
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
        msg_id = result["result"]["message_id"]
        if SHOW_BUTTONS and project:
            _set_last_button_msg(project, msg_id)
        return msg_id

    log("Plain text fallback also failed")
    return None


def _send_document(
    file_bytes: bytes,
    filename: str,
    caption: str = "",
    reply_to: int | None = None,
) -> None:
    """Send a file as a Telegram document using multipart/form-data."""
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
                log(f"sendDocument failed: {result}")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
        log(f"sendDocument error: {e}")


def _answer_callback(callback_id: str, text: str) -> None:
    """Acknowledge a callback query."""
    _telegram_api("answerCallbackQuery", {
        "callback_query_id": callback_id,
        "text": text,
        "show_alert": False,
    })
