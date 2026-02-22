"""Debounce: accumulate rapid-fire events and flush as batch."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from hookline.config import DEBOUNCE_WINDOW, EMOJI
from hookline.formatting import _esc
from hookline.project import _project_label
from hookline.state import _locked_update, _read_state


def _debounce_accumulate(project: str, event: dict) -> None:
    """Add an event to the debounce batch."""
    event_name = event.get("hook_event_name", "Unknown")
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

    def updater(state: dict) -> dict | None:
        nonlocal flushed
        flushed = state
        return None

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
    """Check if there's a pending batch that should be flushed."""
    state = _read_state(project, "debounce.json")
    if not state:
        return False
    last = state.get("last_time", 0)
    return (time.time() - last) > DEBOUNCE_WINDOW
