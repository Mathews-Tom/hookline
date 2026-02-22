"""Extensible command registry for Telegram reply and free-text commands."""
from __future__ import annotations

from collections.abc import Callable

from hookline._log import log
from hookline.config import CHAT_ID, MEMORY_ENABLED, RELAY_ENABLED
from hookline.formatting import _esc, _truncate
from hookline.project import _project_label
from hookline.relay import (
    clear_inbox,
    is_paused,
    list_active_sessions,
    read_inbox,
    set_paused,
    write_inbox,
)
from hookline.telegram import _telegram_api

# Type for command handlers: (project, args, reply_to_msg_id) -> None
CommandHandler = Callable[[str, str, int], None]

# Registry: command_name -> handler
_registry: dict[str, CommandHandler] = {}


def register(name: str) -> Callable[[CommandHandler], CommandHandler]:
    """Decorator to register a command handler."""
    def decorator(fn: CommandHandler) -> CommandHandler:
        _registry[name] = fn
        return fn
    return decorator


def dispatch(command: str, project: str, args: str, reply_to: int) -> bool:
    """Dispatch a command. Returns True if handled, False otherwise."""
    handler = _registry.get(command)
    if handler is None:
        return False
    try:
        handler(project, args, reply_to)
    except Exception as e:
        log(f"Command '{command}' error: {e}")
        _telegram_api("sendMessage", {
            "chat_id": CHAT_ID,
            "text": f"Command error: {_esc(str(e))}",
            "parse_mode": "HTML",
            "reply_to_message_id": reply_to,
        })
    return True


def _reply(text: str, reply_to: int, parse_mode: str = "HTML") -> None:
    """Send a reply message."""
    _telegram_api("sendMessage", {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": parse_mode,
        "reply_to_message_id": reply_to,
    })


# ── Relay Commands ────────────────────────────────────────────────────────────


@register("send")
def _cmd_send(project: str, args: str, reply_to: int) -> None:
    """Queue a message to the active session's inbox."""
    if not RELAY_ENABLED:
        _reply("Relay is disabled. Set <code>relay_enabled: true</code> in hookline.json", reply_to)
        return
    if not args.strip():
        _reply("Usage: <code>send &lt;message&gt;</code>", reply_to)
        return
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    msg_id = write_inbox(project, "telegram", args.strip())
    _reply(f"Queued to <b>{_esc(project)}</b> (id: <code>{msg_id}</code>)", reply_to)


@register("pause")
def _cmd_pause(project: str, args: str, reply_to: int) -> None:
    """Pause the active session."""
    if not RELAY_ENABLED:
        _reply("Relay is disabled.", reply_to)
        return
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    if is_paused(project):
        _reply(f"<b>{_esc(project)}</b> is already paused.", reply_to)
        return
    set_paused(project, paused=True, by="telegram")
    _reply(f"Paused <b>{_esc(project)}</b>. Reply <code>resume</code> to continue.", reply_to)


@register("resume")
def _cmd_resume(project: str, args: str, reply_to: int) -> None:
    """Resume a paused session."""
    if not RELAY_ENABLED:
        _reply("Relay is disabled.", reply_to)
        return
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    if not is_paused(project):
        _reply(f"<b>{_esc(project)}</b> is not paused.", reply_to)
        return
    set_paused(project, paused=False)
    _reply(f"Resumed <b>{_esc(project)}</b>.", reply_to)


@register("sessions")
def _cmd_sessions(project: str, args: str, reply_to: int) -> None:
    """List active sessions with projects."""
    sessions = list_active_sessions()
    if not sessions:
        _reply("No active sessions.", reply_to)
        return
    lines = ["<b>Active Sessions</b>", ""]
    for s in sessions:
        label = _project_label(s["project"])
        status_parts: list[str] = []
        if s.get("paused"):
            status_parts.append("PAUSED")
        unread = s.get("unread_inbox", 0)
        if unread:
            status_parts.append(f"{unread} unread")
        status = f" ({', '.join(status_parts)})" if status_parts else ""
        lines.append(f"  {_esc(label)}{status}")
    _reply("\n".join(lines), reply_to)


@register("inbox")
def _cmd_inbox(project: str, args: str, reply_to: int) -> None:
    """Show unread inbox messages for a project."""
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    messages = read_inbox(project, unread_only=True)
    if not messages:
        _reply(f"No unread messages for <b>{_esc(project)}</b>.", reply_to)
        return
    lines = [f"<b>Inbox — {_esc(project)}</b> ({len(messages)} unread)", ""]
    for msg in messages[-10:]:
        sender = msg.get("sender", "?")
        text = _truncate(msg.get("text", ""), 200)
        ts = msg.get("ts", "")[:19]
        lines.append(f"  [{sender}] {_esc(text)}  <i>{ts}</i>")
    _reply("\n".join(lines), reply_to)


@register("clear")
def _cmd_clear(project: str, args: str, reply_to: int) -> None:
    """Clear all inbox messages for a project."""
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    clear_inbox(project)
    _reply(f"Cleared inbox for <b>{_esc(project)}</b>.", reply_to)


# ── Memory Commands ──────────────────────────────────────────────────────────


def _memory_disabled_reply(reply_to: int) -> None:
    _reply(
        "Memory is disabled. Set <code>memory_enabled: true</code> in hookline.json",
        reply_to,
    )


@register("remember")
def _cmd_remember(project: str, args: str, reply_to: int) -> None:
    """Store a fact or note in project memory."""
    if not MEMORY_ENABLED:
        _memory_disabled_reply(reply_to)
        return
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    if not args.strip():
        _reply("Usage: <code>remember &lt;text&gt;</code>", reply_to)
        return
    from hookline.memory.knowledge import KnowledgeManager
    from hookline.memory.store import get_store
    km = KnowledgeManager(get_store())
    kid = km.remember(project, args.strip())
    _reply(f"Stored in <b>{_esc(project)}</b> memory (id: <code>{kid}</code>)", reply_to)


@register("recall")
def _cmd_recall(project: str, args: str, reply_to: int) -> None:
    """Search project memory by query."""
    if not MEMORY_ENABLED:
        _memory_disabled_reply(reply_to)
        return
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    if not args.strip():
        _reply("Usage: <code>recall &lt;query&gt;</code>", reply_to)
        return
    from hookline.memory.knowledge import KnowledgeManager
    from hookline.memory.store import get_store
    km = KnowledgeManager(get_store())
    results = km.recall(project, args.strip(), limit=10)
    if not results:
        _reply(f"No results for <b>{_esc(args.strip())}</b> in {_esc(project)}.", reply_to)
        return
    lines = [f"<b>Recall — {_esc(project)}</b> ({len(results)} result(s))", ""]
    for msg in results[:10]:
        sender = msg.get("sender", "?")
        text = _truncate(msg.get("text", ""), 200)
        ts = msg.get("ts", "")[:19]
        lines.append(f"  [{sender}] {_esc(text)}  <i>{ts}</i>")
    _reply("\n".join(lines), reply_to)


@register("goals")
def _cmd_goals(project: str, args: str, reply_to: int) -> None:
    """List active goals for a project."""
    if not MEMORY_ENABLED:
        _memory_disabled_reply(reply_to)
        return
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    from hookline.memory.store import get_store
    store = get_store()
    goals = store.get_knowledge(project, category="goal", active_only=True)
    if not goals:
        _reply(f"No active goals for <b>{_esc(project)}</b>.", reply_to)
        return
    lines = [f"<b>Goals — {_esc(project)}</b> ({len(goals)} active)", ""]
    for i, g in enumerate(goals, 1):
        lines.append(f"  {i}. {_esc(_truncate(g['text'], 200))}  <i>(id: {g['id']})</i>")
    _reply("\n".join(lines), reply_to)


@register("context")
def _cmd_context(project: str, args: str, reply_to: int) -> None:
    """Show memory context snapshot for a project."""
    if not MEMORY_ENABLED:
        _memory_disabled_reply(reply_to)
        return
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    from hookline.memory.knowledge import KnowledgeManager
    from hookline.memory.store import get_store
    km = KnowledgeManager(get_store())
    ctx = km.get_context(project, limit=10)
    lines = [f"<b>Context — {_esc(project)}</b>", ""]

    goals = ctx.get("active_goals", [])
    if goals:
        lines.append(f"<b>Goals</b> ({len(goals)}):")
        for g in goals[:5]:
            lines.append(f"  - {_esc(_truncate(g['text'], 150))}")

    facts = ctx.get("facts", [])
    if facts:
        lines.append(f"<b>Facts</b> ({len(facts)}):")
        for f in facts[:5]:
            lines.append(f"  - {_esc(_truncate(f['text'], 150))}")

    msgs = ctx.get("recent_messages", [])
    if msgs:
        lines.append(f"<b>Recent</b> ({len(msgs)} messages)")

    if len(lines) <= 2:
        _reply(f"No memory data for <b>{_esc(project)}</b>.", reply_to)
        return
    _reply("\n".join(lines), reply_to)


@register("forget")
def _cmd_forget(project: str, args: str, reply_to: int) -> None:
    """Deactivate a memory entry by ID."""
    if not MEMORY_ENABLED:
        _memory_disabled_reply(reply_to)
        return
    if not project:
        _reply("No active session found for this thread.", reply_to)
        return
    if not args.strip():
        _reply("Usage: <code>forget &lt;id&gt;</code>", reply_to)
        return
    try:
        kid = int(args.strip())
    except ValueError:
        _reply("ID must be a number.", reply_to)
        return
    from hookline.memory.knowledge import KnowledgeManager
    from hookline.memory.store import get_store
    km = KnowledgeManager(get_store())
    if km.forget(project, kid):
        _reply(f"Deactivated memory entry <code>{kid}</code>.", reply_to)
    else:
        _reply(f"Entry <code>{kid}</code> not found or already inactive.", reply_to)
