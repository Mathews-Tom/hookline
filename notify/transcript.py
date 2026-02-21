"""Transcript reading and summary extraction."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from notify._log import log

# Cache transcript summaries by (path, mtime)
_transcript_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _read_transcript_tail(transcript_path: str, tail_bytes: int = 32768) -> list[dict]:
    """Read and parse the last N bytes of a JSONL transcript."""
    if not transcript_path:
        return []
    path = Path(transcript_path)
    if not path.exists():
        return []
    try:
        size = path.stat().st_size
        if size > 10 * 1024 * 1024:
            log(f"Transcript too large ({size} bytes), skipping extraction")
            return []
        read_size = min(size, tail_bytes)
        with path.open("rb") as f:
            if size > read_size:
                f.seek(-read_size, 2)
            raw = f.read().decode("utf-8", errors="replace")
        lines = raw.split("\n")
        if size > read_size:
            lines = lines[1:]
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
    """Extract structured summary from transcript tail."""
    transcript_path = event.get("transcript_path", "")

    # Check cache by (path, mtime)
    if transcript_path:
        try:
            mtime = Path(transcript_path).stat().st_mtime
            cached = _transcript_cache.get(transcript_path)
            if cached and cached[0] == mtime:
                return cached[1]
        except OSError:
            pass

    entries = _read_transcript_tail(transcript_path)
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

            if role == "assistant" and block.get("type") == "text" and len(messages) < 3:
                text = block.get("text", "").strip()
                if text:
                    messages.append(text)

            if role == "assistant" and block.get("type") == "tool_use":
                tool_name = block.get("name", "unknown")
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

            if role == "user" and block.get("type") == "tool_result":
                if block.get("is_error"):
                    err_content = block.get("content", "")
                    if isinstance(err_content, str) and err_content.strip():
                        errors.append(err_content.strip()[:200])
                    elif isinstance(err_content, list):
                        for sub in err_content:
                            if isinstance(sub, dict) and sub.get("type") == "text":
                                errors.append(sub.get("text", "").strip()[:200])

    tool_summary = ""
    if tool_counts:
        total = sum(tool_counts.values())
        sorted_tools = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
        top = ", ".join(f"{c} {n}" for n, c in sorted_tools[:5])
        tool_summary = f"{total} tool calls: {top}"

    result = {
        "messages": messages,
        "tool_summary": tool_summary,
        "errors": errors[:3],
    }

    if transcript_path:
        try:
            mtime = Path(transcript_path).stat().st_mtime
            _transcript_cache[transcript_path] = (mtime, result)
        except OSError:
            pass

    return result
