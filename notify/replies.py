"""Reply message handlers: transcript queries via Telegram replies."""
from __future__ import annotations

import json
from typing import Any

from notify.config import CHAT_ID, REPLY_COMMANDS
from notify.formatting import _esc, _truncate
from notify.project import _project_label
from notify.telegram import _send_document, _telegram_api
from notify.threads import _find_thread_by_message_id
from notify.transcript import _extract_transcript_summary, _read_transcript_tail


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
