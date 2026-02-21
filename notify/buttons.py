"""Inline button building and last-button state tracking."""
from __future__ import annotations

from notify.session import _session_key
from notify.state import _clear_state, _read_state, _write_state


def _get_last_button_msg(project: str) -> int | None:
    """Get the message_id of the last message with inline buttons."""
    state = _read_state(project, "last_buttons.json")
    session = _session_key(project)
    if state.get("session") == session:
        return state.get("message_id")
    return None


def _set_last_button_msg(project: str, message_id: int) -> None:
    """Store the message_id of the latest message with inline buttons."""
    _write_state(project, "last_buttons.json", {
        "session": _session_key(project),
        "message_id": message_id,
    })


def _clear_last_button_msg(project: str) -> None:
    """Clear the last button message tracking."""
    _clear_state(project, "last_buttons.json")


def _build_buttons(project: str, is_final: bool) -> dict:
    """Build inline keyboard markup based on event context."""
    if is_final:
        return {
            "inline_keyboard": [
                [
                    {"text": "🔇 Mute Project", "callback_data": f"mute_proj_{project}"},
                    {"text": "📌 New Thread", "callback_data": f"reset_{project}"},
                ],
            ]
        }
    return {
        "inline_keyboard": [
            [
                {"text": "🔇 Mute 30m", "callback_data": f"mute_30_{project}"},
                {"text": "🔇 Mute Project", "callback_data": f"mute_proj_{project}"},
            ],
        ]
    }
