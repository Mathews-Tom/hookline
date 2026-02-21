"""Tool approval: pipe management, PreToolUse hook, callback handling, audit."""
from __future__ import annotations

import errno
import json
import os
import select
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from notify._log import log
from notify.config import (
    APPROVAL_ENABLED,
    APPROVAL_TIMEOUT,
    APPROVAL_USER,
    AUDIT_LOG,
    CHAT_ID,
    DRY_RUN,
    STATE_DIR,
)
from notify.formatting import _esc, _truncate
from notify.project import _project_label
from notify.session import _extract_project, _is_enabled, _session_duration
from notify.state import _clear_state, _is_serve_running, _read_state, _write_state
from notify.telegram import _answer_callback, _telegram_api, send_message
from notify.threads import _get_thread_id


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
        log(f"Audit log write error: {e}")


def _output_decision(decision: str, reason: str = "") -> None:
    """Output a hook decision as JSON to stdout for Claude Code."""
    output: dict[str, str] = {"decision": decision}
    if reason:
        output["reason"] = reason
    print(json.dumps(output))


def _format_approval_message(event: dict, project: str) -> str:
    """Format the approval request message for Telegram."""
    tool_name = event.get("tool_name", "unknown")
    tool_input = event.get("tool_input", {})
    label = _project_label(project)
    duration = _session_duration(project)

    input_preview = ""
    if tool_name == "Bash" and isinstance(tool_input, dict):
        input_preview = tool_input.get("command", "")[:200]
    elif tool_name == "Write" and isinstance(tool_input, dict):
        input_preview = tool_input.get("file_path", "")
    elif tool_name == "Edit" and isinstance(tool_input, dict):
        input_preview = tool_input.get("file_path", "")
    elif isinstance(tool_input, dict):
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
        emoji_char = "✅"
        status = "Approved"
    elif decision == "block":
        emoji_char = "❌"
        status = "Blocked"
    else:
        emoji_char = "⏰"
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
        f"<b>┌─ {emoji_char} {status} ─────── {_esc(label)}</b>",
        f"│ Tool: <b>{_esc(tool_name)}</b>",
    ]
    if input_preview:
        lines.append(f"│ <code>{_esc(_truncate(input_preview, 200))}</code>")

    by_str = f"by {_esc(user)} · " if user else ""
    lines.append(f"<i>└─ {status} {by_str}{ts}</i>")

    return "\n".join(lines)


def _send_threaded(
    text: str,
    project: str,
    transcript_path: str = "",
    is_final: bool = False,
) -> None:
    """Send a message with thread grouping."""
    reply_to = _get_thread_id(project)
    message_id = send_message(text, project=project, reply_to=reply_to, is_final=is_final)

    from notify.threads import _set_thread_id  # avoid circular at module level
    if message_id and reply_to is None:
        _set_thread_id(project, message_id, transcript_path=transcript_path)

    if message_id:
        log(f"Sent notification (msg_id={message_id})")
    else:
        log("Failed to send notification")


def _handle_pre_tool_use(event: dict) -> None:
    """Handle PreToolUse hook: send approval request, block on pipe, output decision."""
    project = _extract_project(event)
    tool_name = event.get("tool_name", "unknown")

    if not APPROVAL_ENABLED:
        return

    if DRY_RUN:
        text = _format_approval_message(event, project)
        print(f"[dry-run] approval request for {tool_name}:")
        print(text)
        _output_decision("approve", "dry-run auto-approve")
        return

    if not _is_serve_running():
        log("Serve daemon not running — skipping approval, auto-blocking")
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

    try:
        os.mkfifo(pipe_path)
    except OSError as e:
        log(f"Failed to create approval pipe: {e}")
        _output_decision("block", f"Internal error: {e}")
        return

    try:
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
            log("Failed to send approval message")
            _output_decision("block", "Failed to send approval request")
            return

        _write_state("_approvals", f"{approval_id}.json", {
            "approval_id": approval_id,
            "message_id": msg_id,
            "project": project,
            "tool_name": tool_name,
            "tool_input": event.get("tool_input", {}),
            "pipe_path": str(pipe_path),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "event": {k: v for k, v in event.items() if k != "transcript_path"},
        })

        log(f"Waiting for approval decision (id={approval_id}, timeout={APPROVAL_TIMEOUT}s)")
        fd = os.open(str(pipe_path), os.O_RDONLY | os.O_NONBLOCK)
        try:
            ready, _, _ = select.select([fd], [], [], APPROVAL_TIMEOUT)
            if ready:
                decision_raw = os.read(fd, 1024).decode("utf-8").strip()
            else:
                decision_raw = ""
        finally:
            os.close(fd)

        if decision_raw in ("approve", "block"):
            decision = decision_raw
        else:
            decision = "block"

        reason = "Timed out" if not decision_raw else ""
        user_name = ""

        approval_state = _read_state("_approvals", f"{approval_id}.json")
        if approval_state.get("decided_by"):
            user_name = approval_state["decided_by"]
        if approval_state.get("reason"):
            reason = approval_state["reason"]

        if msg_id:
            result_text = _format_approval_result(event, project, decision, user_name)
            _telegram_api("editMessageText", {
                "chat_id": CHAT_ID,
                "message_id": msg_id,
                "text": result_text,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": []},
            })

        _audit_log_entry({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "approval_id": approval_id,
            "project": project,
            "tool_name": tool_name,
            "decision": decision,
            "decided_by": user_name,
            "reason": reason,
        })

        _output_decision(decision, reason)

    finally:
        pipe_path.unlink(missing_ok=True)
        _clear_state("_approvals", f"{approval_id}.json")


def _handle_approval_callback(callback: dict) -> None:
    """Handle an approval button press from the serve daemon."""
    data = callback.get("data", "")
    callback_id = callback.get("id", "")
    sender_id = str(callback.get("from", {}).get("id", ""))
    user_name = callback.get("from", {}).get("first_name", "unknown")

    if sender_id != APPROVAL_USER:
        _answer_callback(callback_id, "Not authorized for approvals")
        log(f"Rejected approval from {sender_id} (expected {APPROVAL_USER})")
        return

    if data.startswith("approve_"):
        approval_id = data[8:]
        decision = "approve"
    elif data.startswith("block_"):
        approval_id = data[6:]
        decision = "block"
    else:
        _answer_callback(callback_id, "Unknown action")
        return

    state = _read_state("_approvals", f"{approval_id}.json")
    if not state:
        _answer_callback(callback_id, "Approval expired or already handled")
        return

    pipe_path = state.get("pipe_path", "")
    if not pipe_path or not Path(pipe_path).exists():
        _answer_callback(callback_id, "Approval expired (pipe gone)")
        return

    state["decided_by"] = user_name
    state["decision"] = decision
    _write_state("_approvals", f"{approval_id}.json", state)

    try:
        fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, decision.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as e:
        if e.errno == errno.ENXIO:
            created_at = state.get("created_at", "unknown")
            log(f"Approval pipe has no reader (hook timed out, created_at={created_at})")
            _answer_callback(callback_id, "Approval expired (hook timed out)")
        else:
            log(f"Failed to write to approval pipe: {e}")
            _answer_callback(callback_id, f"Error: {e}")
        return

    emoji_char = "✅" if decision == "approve" else "❌"
    _answer_callback(callback_id, f"{emoji_char} {decision.title()}d")
    print(f"[notify-serve] {user_name} {decision}d {state.get('tool_name', '?')} (id={approval_id})")
