"""Configuration: paths, credentials, settings, constants."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# ── Paths ────────────────────────────────────────────────────────────────────

CLAUDE_DIR = Path.home() / ".claude"
SENTINEL_DIR = CLAUDE_DIR
STATE_DIR = CLAUDE_DIR / "notify-state"
NOTIFY_CONFIG_PATH = CLAUDE_DIR / "notify-config.json"
PROJECT_CONFIG_PATH = CLAUDE_DIR / "notify-projects.json"
SERVE_PID_FILE = STATE_DIR / "serve.pid"
AUDIT_LOG = STATE_DIR / "audit.jsonl"

# ── Credentials ──────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ── Config File Loader ───────────────────────────────────────────────────────

_notify_config: dict | None = None


def _load_config() -> dict[str, Any]:
    """Load ~/.claude/notify-config.json (cached per invocation)."""
    global _notify_config
    if _notify_config is None:
        try:
            _notify_config = json.loads(NOTIFY_CONFIG_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            _notify_config = {}
    return _notify_config  # type: ignore[return-value]


def _cfg_bool(env_key: str, config_key: str, default: bool) -> bool:
    """Read a boolean: env var ("1"/"0") → config file (true/false) → default."""
    env = os.environ.get(env_key)
    if env is not None:
        return env == "1"
    val = _load_config().get(config_key)
    if isinstance(val, bool):
        return val
    return default


def _cfg_int(env_key: str, config_key: str, default: int) -> int:
    """Read an integer: env var → config file → default."""
    env = os.environ.get(env_key)
    if env is not None:
        return int(env)
    val = _load_config().get(config_key)
    if isinstance(val, int):
        return val
    return default


def _cfg_str(env_key: str, config_key: str, default: str) -> str:
    """Read a string: env var → config file → default."""
    env = os.environ.get(env_key)
    if env is not None:
        return env
    val = _load_config().get(config_key)
    if isinstance(val, str):
        return val
    return default


def _cfg_suppress(env_key: str, config_key: str) -> set[str]:
    """Read suppress list: env var (comma-separated) → config file (list) → empty set."""
    env = os.environ.get(env_key)
    if env is not None:
        return set(env.split(",")) - {""}
    val = _load_config().get(config_key)
    if isinstance(val, list):
        return {str(v) for v in val if v}
    return set()


# ── Preferences ──────────────────────────────────────────────────────────────

SUPPRESS = _cfg_suppress("CLAUDE_NOTIFY_SUPPRESS", "suppress")
MIN_SESSION_AGE = _cfg_int("CLAUDE_NOTIFY_MIN_AGE", "min_session_age", 0)
SHOW_BUTTONS = _cfg_bool("CLAUDE_NOTIFY_BUTTONS", "show_buttons", True)
DEBOUNCE_WINDOW = _cfg_int("CLAUDE_NOTIFY_DEBOUNCE", "debounce_window", 30)

# Tool approval settings
APPROVAL_ENABLED = _cfg_bool("CLAUDE_NOTIFY_APPROVAL", "approval_enabled", False)
APPROVAL_USER = _cfg_str("CLAUDE_NOTIFY_APPROVAL_USER", "approval_user", "") or CHAT_ID
APPROVAL_TIMEOUT = _cfg_int("CLAUDE_NOTIFY_APPROVAL_TIMEOUT", "approval_timeout", 120)

# ── CLI Mode ─────────────────────────────────────────────────────────────────

DRY_RUN = "--dry-run" in sys.argv

# ── Constants ────────────────────────────────────────────────────────────────

DEBOUNCE_EVENTS = {"SubagentStop", "TeammateIdle"}
FULL_FORMAT_EVENTS = {"Stop", "TaskCompleted", "Notification"}

EMOJI: dict[str, str] = {
    "Stop": "✅",
    "Notification": "⏳",
    "TeammateIdle": "💤",
    "TaskCompleted": "🎯",
    "SubagentStop": "📋",
}

REPLY_COMMANDS: dict[str, str] = {
    "log": "Last 3 assistant messages with tool summary",
    "details": "Last 3 assistant messages with tool summary",
    "full": "Upload transcript tail as .txt document",
    "errors": "Extract and send only error blocks",
    "tools": "List all tool calls made in the session",
    "help": "Show available commands",
}
