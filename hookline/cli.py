"""Unified CLI dispatcher for hookline."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_project(explicit: str | None) -> str:
    """Resolve project name: explicit arg > cwd basename > 'all'."""
    if explicit:
        return explicit
    cwd_name = Path.cwd().name
    if cwd_name:
        return cwd_name
    return "all"


def _sentinel_global() -> Path:
    from hookline.config import SENTINEL_DIR
    return SENTINEL_DIR / "hookline-enabled"


def _sentinel_project(project: str) -> Path:
    from hookline.config import SENTINEL_DIR
    return SENTINEL_DIR / f"hookline-enabled.{project}"


def _do_on(project: str | None) -> None:
    """Enable notifications (global or scoped)."""
    resolved = _resolve_project(project)
    ts = _now_iso()
    if resolved == "all":
        path = _sentinel_global()
        path.write_text(ts)
        print(f"🔔 hookline ON (global) — {ts}")
    else:
        path = _sentinel_project(resolved)
        path.write_text(ts)
        print(f"🔔 hookline ON for '{resolved}' — {ts}")


def _do_off(project: str | None) -> None:
    """Disable notifications (global or scoped)."""
    resolved = _resolve_project(project)
    if resolved == "all":
        path = _sentinel_global()
        if path.exists():
            path.unlink()
            print("🔕 hookline OFF (global)")
        else:
            print("🔕 hookline already OFF (global)")
    else:
        path = _sentinel_project(resolved)
        if path.exists():
            path.unlink()
            print(f"🔕 hookline OFF for '{resolved}'")
        else:
            print(f"🔕 hookline already OFF for '{resolved}'")


def _do_status() -> None:
    """Print enabled/disabled state for all sentinels plus daemon status."""
    from hookline.config import SENTINEL_DIR
    from hookline.state import _is_serve_running

    global_sentinel = _sentinel_global()
    project_sentinels = sorted(SENTINEL_DIR.glob("hookline-enabled.*"))

    any_active = False

    print("📊 hookline status")
    print("──────────────────────────────────────")

    if global_sentinel.exists():
        ts = global_sentinel.read_text().strip()
        print(f"  🔔 global     ON  (since {ts})")
        any_active = True
    else:
        print("  🔕 global     OFF")

    for p in project_sentinels:
        name = p.name.removeprefix("hookline-enabled.")
        ts = p.read_text().strip()
        print(f"  🔔 {name:10s} ON  (since {ts})")
        any_active = True

    if not any_active:
        print("  🔕 all notifications disabled")

    print()
    daemon = _is_serve_running()
    print(f"  {'🟢' if daemon else '🔴'} daemon     {'running' if daemon else 'stopped'}")

    from hookline.config import RELAY_ENABLED
    if RELAY_ENABLED:
        from hookline.relay import list_active_sessions
        sessions = list_active_sessions()
        print(f"  🟢 relay      ON ({len(sessions)} session(s))")
        for s in sessions:
            status_parts: list[str] = []
            if s.get("paused"):
                status_parts.append("paused")
            unread = s.get("unread_inbox", 0)
            if unread:
                status_parts.append(f"{unread} unread")
            extra = f" ({', '.join(status_parts)})" if status_parts else ""
            print(f"    └─ {s['project']}{extra}")
    else:
        print("  ⚪ relay      OFF")

    from hookline.config import MEMORY_ENABLED
    if MEMORY_ENABLED:
        try:
            from hookline.memory.store import get_store
            get_store()  # Verify store is accessible
            print("  🟢 memory     ON")
        except Exception:
            print("  🟡 memory     ON (store unavailable)")
    else:
        print("  ⚪ memory     OFF")

    from hookline.config import SCHEDULE_ENABLED
    if SCHEDULE_ENABLED:
        from hookline.scheduler import get_status
        tasks = get_status()
        print(f"  🟢 scheduler  ON ({len(tasks)} task(s))")
    else:
        print("  ⚪ scheduler  OFF")

    print("──────────────────────────────────────")


def _do_serve() -> None:
    """Start the Telegram polling server."""
    from hookline.serve import serve
    serve()


def _do_health() -> None:
    """Run health check diagnostics."""
    from hookline.__main__ import health_check
    health_check()


def _do_version() -> None:
    """Print version string."""
    from hookline import __version__
    print(f"🎣 hookline {__version__}")


def _do_reset(project: str | None) -> None:
    """Clear thread/tasks/debounce state for a project or all projects."""
    from hookline.config import STATE_DIR
    from hookline.state import _clear_state

    resolved = _resolve_project(project)

    if resolved == "all":
        if not STATE_DIR.exists():
            print("⚪ no state to reset")
            return
        cleared = 0
        for project_dir in STATE_DIR.iterdir():
            if not project_dir.is_dir():
                continue
            proj = project_dir.name
            for fname in ("thread.json", "tasks.json", "debounce.json", "mute.json"):
                _clear_state(proj, fname)
            cleared += 1
        print(f"🧹 reset state for {cleared} project(s)")
    else:
        for fname in ("thread.json", "tasks.json", "debounce.json", "mute.json"):
            _clear_state(resolved, fname)
        print(f"🧹 reset state for '{resolved}'")


def _do_config() -> None:
    """Print effective configuration."""
    from hookline.config import (
        APPROVAL_ENABLED,
        APPROVAL_TIMEOUT,
        APPROVAL_USER,
        BOT_TOKEN,
        CHAT_ID,
        DEBOUNCE_WINDOW,
        MIN_SESSION_AGE,
        NOTIFY_CONFIG_PATH,
        SENTINEL_DIR,
        SERVE_PID_FILE,
        SHOW_BUTTONS,
        STATE_DIR,
        SUPPRESS,
    )

    token_display = (BOT_TOKEN[:8] + "***") if BOT_TOKEN else "(not set)"
    chat_display = CHAT_ID if CHAT_ID else "(not set)"
    suppress_display = ", ".join(sorted(SUPPRESS)) if SUPPRESS else "(none)"

    print("⚙️  hookline config")
    print("──────────────────────────────────────")
    print(f"  🔑 bot_token:        {token_display}")
    print(f"  💬 chat_id:          {chat_display}")
    print(f"  📁 sentinel_dir:     {SENTINEL_DIR}")
    print(f"  📁 state_dir:        {STATE_DIR}")
    print(f"  📄 config_file:      {NOTIFY_CONFIG_PATH}")
    print(f"  📄 serve_pid_file:   {SERVE_PID_FILE}")
    print(f"  ⏱️  min_session_age:  {MIN_SESSION_AGE}s")
    print(f"  ⏱️  debounce_window:  {DEBOUNCE_WINDOW}s")
    print(f"  🔘 show_buttons:     {SHOW_BUTTONS}")
    print(f"  🚫 suppress:         {suppress_display}")
    print(f"  🛡️  approval_enabled: {APPROVAL_ENABLED}")
    print(f"  👤 approval_user:    {approval_display(APPROVAL_USER)}")
    print(f"  ⏱️  approval_timeout: {APPROVAL_TIMEOUT}s")

    from hookline.config import RELAY_ENABLED, RELAY_MODE
    print(f"  📡 relay_enabled:    {RELAY_ENABLED}")
    print(f"  📡 relay_mode:       {RELAY_MODE}")

    from hookline.config import MEMORY_DB_PATH, MEMORY_ENABLED, MEMORY_MAX_ENTRIES
    print(f"  🧠 memory_enabled:   {MEMORY_ENABLED}")
    print(f"  🧠 memory_db_path:   {MEMORY_DB_PATH or '(default)'}")
    print(f"  🧠 memory_max_entries: {MEMORY_MAX_ENTRIES}")

    from hookline.config import BRIEFING_CRON, CHECKIN_INTERVAL, DIGEST_CRON, SCHEDULE_ENABLED
    print(f"  📅 schedule_enabled: {SCHEDULE_ENABLED}")
    print(f"  📅 briefing_cron:    {BRIEFING_CRON}")
    print(f"  📅 digest_cron:      {DIGEST_CRON}")
    print(f"  📅 checkin_interval: {CHECKIN_INTERVAL}m")
    print("──────────────────────────────────────")


def approval_display(val: str) -> str:
    """Mask approval user value if it looks like a numeric chat ID."""
    if val and val.lstrip("-").isdigit():
        return val[:4] + "***"
    return val if val else "(not set)"


def _do_doctor() -> None:
    """Extended diagnostics: health check plus filesystem and config verification."""
    from hookline.__main__ import health_check
    from hookline.config import NOTIFY_CONFIG_PATH, SENTINEL_DIR, STATE_DIR

    print("🩺 Extended diagnostics")
    print("──────────────────────────────────────")

    _ok = "✅"
    _no = "❌"

    print(f"  {_ok if SENTINEL_DIR.exists() else _no} sentinel_dir: {SENTINEL_DIR}")
    print(f"  {_ok if STATE_DIR.exists() else _no} state_dir:    {STATE_DIR}")
    print(f"  {_ok if NOTIFY_CONFIG_PATH.exists() else _no} config_file:  {NOTIFY_CONFIG_PATH}")

    sentinels = list(SENTINEL_DIR.glob("hookline-enabled*"))
    print(f"  📋 active sentinels: {len(sentinels)}")
    for s in sorted(sentinels):
        print(f"     └─ {s.name}")

    print()
    health_check()


def _do_migrate() -> None:
    """Run migration from notify to hookline."""
    from hookline.migrate import migrate
    migrate()


def _print_usage() -> None:
    from hookline import __version__
    print(
        f"🎣 hookline {__version__}\n"
        "\n"
        "usage: hookline <command> [args] [--project NAME] [--dry-run]\n"
        "\n"
        "commands:\n"
        "  🔔 on       enable notifications (global or --project scoped)\n"
        "  🔕 off      disable notifications\n"
        "  📊 status   show enabled state and daemon status\n"
        "  🤖 serve    start Telegram polling daemon\n"
        "  🩺 health   run self-diagnostics\n"
        "  🩺 doctor   extended diagnostics\n"
        "  🧹 reset    clear thread/tasks/debounce state\n"
        "  ⚙️  config   print effective configuration\n"
        "  🔄 migrate  migrate from notify to hookline\n"
        "  🏷️  version  print version\n"
        "\n"
        "flags:\n"
        "  --project NAME  scope on/off/reset to a specific project\n"
        "  --serve         alias for the serve command\n"
        "  --version       alias for the version command\n"
        "  --dry-run       process hooks without sending messages\n"
    )


# All recognised subcommands and their flag aliases
_SUBCOMMANDS: frozenset[str] = frozenset({
    "on", "off", "status", "serve", "health", "doctor",
    "reset", "config", "migrate", "version",
})

_FLAG_MAP: dict[str, str] = {
    "--serve": "serve",
    "--on": "on",
    "--off": "off",
    "--status": "status",
    "--health": "health",
    "--doctor": "doctor",
    "--reset": "reset",
    "--config": "config",
    "--migrate": "migrate",
    "--version": "version",
}


def cli_main() -> None:
    """Unified CLI entry point.

    Delegates to main() for hook event processing when stdin is not a tty
    and no subcommand is present. Otherwise dispatches CLI subcommands.
    """
    args = sys.argv[1:]

    # --dry-run is consumed by config.py at import time; strip it from dispatch args
    args = [a for a in args if a != "--dry-run"]

    # --version shortcut before full parse
    if "--version" in args or "-V" in args:
        _do_version()
        return

    # Detect hook-event processing mode: no CLI intent and stdin has piped data
    has_subcommand = any(a in _SUBCOMMANDS or a in _FLAG_MAP for a in args)

    if not has_subcommand and not sys.stdin.isatty():
        from hookline.__main__ import main
        main()
        return

    # Parse --project flag and collect remaining args
    project_arg: str | None = None
    clean_args: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args):
            project_arg = args[i + 1]
            i += 2
        else:
            clean_args.append(args[i])
            i += 1

    if not clean_args:
        _print_usage()
        return

    cmd = _FLAG_MAP.get(clean_args[0], clean_args[0])
    # Positional project after on/off/reset: `hookline on myproject`
    positional_project: str | None = clean_args[1] if len(clean_args) > 1 else None
    # --project flag takes precedence over positional
    effective_project = project_arg or positional_project

    if cmd == "on":
        _do_on(effective_project)
    elif cmd == "off":
        _do_off(effective_project)
    elif cmd == "status":
        _do_status()
    elif cmd == "serve":
        _do_serve()
    elif cmd == "health":
        _do_health()
    elif cmd == "doctor":
        _do_doctor()
    elif cmd == "reset":
        _do_reset(effective_project)
    elif cmd == "config":
        _do_config()
    elif cmd == "migrate":
        _do_migrate()
    elif cmd == "version":
        _do_version()
    else:
        print(f"❌ hookline: unknown command '{cmd}'", file=sys.stderr)
        _print_usage()
        sys.exit(1)
