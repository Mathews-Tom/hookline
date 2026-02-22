"""Message formatting: HTML escaping, full/compact event formats."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from hookline.config import EMOJI
from hookline.project import _project_label
from hookline.session import _session_duration
from hookline.tasks import _track_task
from hookline.transcript import _extract_transcript_summary


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


def _strip_html(text: str) -> str:
    """Crude HTML tag stripper for plain text fallback."""
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def format_full(event_name: str, event: dict, project: str) -> str:
    """Format a full event with box-drawing headers and blockquote body."""
    emoji = EMOJI.get(event_name, "🔔")
    label = _project_label(project)
    ts = datetime.now(timezone.utc).strftime("%H:%M UTC")
    duration = _session_duration(project)

    header = f"<b>┌─ {emoji} {_esc(event_name)} ─────── {_esc(label)}</b>"
    body = _format_body(event_name, event, project)

    footer_parts = [ts]
    if duration:
        footer_parts.append(f"⏱ {duration}")
    footer = f"<i>└─ {' ── '.join(footer_parts)}</i>"

    return f"{header}\n{body}\n{footer}"


def format_compact(event_name: str, event: dict, project: str) -> str:
    """Format a compact single-line event."""
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

            msgs = summary.get("messages", [])
            if msgs:
                lines.append(_esc(_truncate(msgs[0], 250)))
                for extra in msgs[1:]:
                    lines.append(f"<i>{_esc(_truncate(extra, 150))}</i>")

            tool_sum = summary.get("tool_summary", "")
            if tool_sum:
                lines.append(f"🔧 {_esc(tool_sum)}")

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
