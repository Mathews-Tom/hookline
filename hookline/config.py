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
STATE_DIR = CLAUDE_DIR / "hookline-state"
NOTIFY_CONFIG_PATH = CLAUDE_DIR / "hookline.json"
PROJECT_CONFIG_PATH = CLAUDE_DIR / "hookline-projects.json"
SERVE_PID_FILE = STATE_DIR / "serve.pid"
AUDIT_LOG = STATE_DIR / "audit.jsonl"

# ── Credentials ──────────────────────────────────────────────────────────────

BOT_TOKEN = os.environ.get("HOOKLINE_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("HOOKLINE_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")


def validate_credentials() -> list[str]:
    """Validate BOT_TOKEN and CHAT_ID formats. Returns list of error strings."""
    errors: list[str] = []
    if BOT_TOKEN and ":" not in BOT_TOKEN:
        errors.append("BOT_TOKEN: expected format digits:alphanumeric (e.g. 123456:ABCdef...)")
    if CHAT_ID and not CHAT_ID.lstrip("-").isdigit():
        errors.append("CHAT_ID: expected numeric value")
    return errors

# ── Config File Loader ───────────────────────────────────────────────────────

_hookline_config: dict | None = None


def _load_config() -> dict[str, Any]:
    """Load ~/.claude/hookline.json (cached per invocation)."""
    global _hookline_config
    if _hookline_config is None:
        try:
            _hookline_config = json.loads(NOTIFY_CONFIG_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            _hookline_config = {}
    return _hookline_config  # type: ignore[return-value]


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

SUPPRESS = _cfg_suppress("HOOKLINE_SUPPRESS", "suppress")
MIN_SESSION_AGE = _cfg_int("HOOKLINE_MIN_AGE", "min_session_age", 0)
SHOW_BUTTONS = _cfg_bool("HOOKLINE_BUTTONS", "show_buttons", True)
DEBOUNCE_WINDOW = _cfg_int("HOOKLINE_DEBOUNCE", "debounce_window", 30)

# Tool approval settings
APPROVAL_ENABLED = _cfg_bool("HOOKLINE_APPROVAL", "approval_enabled", False)
APPROVAL_USER = _cfg_str("HOOKLINE_APPROVAL_USER", "approval_user", "") or CHAT_ID
APPROVAL_TIMEOUT = _cfg_int("HOOKLINE_APPROVAL_TIMEOUT", "approval_timeout", 120)

# Relay settings
RELAY_ENABLED = _cfg_bool("HOOKLINE_RELAY", "relay_enabled", False)
RELAY_MODE = _cfg_str("HOOKLINE_RELAY_MODE", "relay_mode", "inbox")

# Memory settings
MEMORY_ENABLED = _cfg_bool("HOOKLINE_MEMORY", "memory_enabled", False)
MEMORY_DB_PATH = _cfg_str("HOOKLINE_MEMORY_DB", "memory_db_path", "")
MEMORY_MAX_ENTRIES = _cfg_int("HOOKLINE_MEMORY_MAX", "memory_max_entries", 10000)

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
    "send": "Queue a message to the active session's inbox",
    "pause": "Pause the active session (blocks next PreToolUse)",
    "resume": "Resume a paused session",
    "sessions": "List active sessions with projects",
    "inbox": "Show unread inbox messages for a project",
    "clear": "Clear all inbox messages for a project",
    "remember": "Store a fact or note in project memory",
    "recall": "Search project memory by query",
    "goals": "List active goals for a project",
    "context": "Show memory context snapshot for a project",
    "forget": "Deactivate a memory entry by ID",
    "help": "Show available commands",
}
