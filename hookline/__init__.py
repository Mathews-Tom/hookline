"""hookline — Claude Code ↔ Telegram relay."""
from __future__ import annotations

__version__ = "4.3.0"

# Re-export the primary entry points
from hookline._log import log as _log  # noqa: F401
from hookline.approval import _handle_pre_tool_use, _send_threaded  # noqa: F401
from hookline.buttons import _build_buttons, _clear_last_button_msg, _get_last_button_msg, _set_last_button_msg  # noqa: F401
from hookline.config import (  # noqa: F401
    APPROVAL_ENABLED,
    APPROVAL_TIMEOUT,
    APPROVAL_USER,
    AUDIT_LOG,
    BOT_TOKEN,
    CHAT_ID,
    CLAUDE_DIR,
    DEBOUNCE_EVENTS,
    DEBOUNCE_WINDOW,
    DRY_RUN,
    EMOJI,
    FULL_FORMAT_EVENTS,
    MIN_SESSION_AGE,
    NOTIFY_CONFIG_PATH,
    PROJECT_CONFIG_PATH,
    REPLY_COMMANDS,
    SENTINEL_DIR,
    SERVE_PID_FILE,
    SHOW_BUTTONS,
    STATE_DIR,
    SUPPRESS,
    _cfg_bool,
    _cfg_int,
    _cfg_str,
    _cfg_suppress,
    _load_config,
)
from hookline.debounce import _debounce_accumulate, _debounce_flush, _debounce_should_flush  # noqa: F401
from hookline.formatting import _esc, _format_body, _strip_html, _truncate, format_compact, format_full  # noqa: F401
from hookline.project import _get_project_config, _project_emoji, _project_label  # noqa: F401
from hookline.replies import _handle_reply_message  # noqa: F401
from hookline.serve import serve  # noqa: F401
from hookline.session import (  # noqa: F401
    _extract_project,
    _is_enabled,
    _is_muted,
    _sentinel_path,
    _sentinel_timestamp,
    _session_age_seconds,
    _session_duration,
    _session_key,
)
from hookline.state import _clear_state, _is_serve_running, _locked_update, _read_state, _state_dir, _write_state  # noqa: F401
from hookline.tasks import _clear_tasks, _track_task  # noqa: F401
from hookline.telegram import _answer_callback, _remove_buttons, _send_document, _telegram_api, send_message  # noqa: F401
from hookline.threads import _clear_thread, _find_thread_by_message_id, _get_thread_id, _set_thread_id  # noqa: F401
from hookline.transcript import _extract_transcript_summary, _read_transcript_tail, _transcript_cache  # noqa: F401
from hookline.relay import (  # noqa: F401
    clear_inbox,
    is_paused,
    list_active_sessions,
    mark_read,
    read_inbox,
    set_paused,
    write_inbox,
)
from hookline.commands import dispatch as dispatch_command, register as register_command  # noqa: F401
