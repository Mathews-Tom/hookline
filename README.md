# hookline

**Claude Code ↔ Telegram relay — notifications, bidirectional messaging, persistent memory, and proactive features.**

`hookline v4.3.0` — stdlib-only Python package, zero runtime dependencies on the hook path.

---

## Overview

hookline connects Claude Code sessions to Telegram with four layers of functionality:

| Layer | Feature | Version |
|-------|---------|---------|
| Notifications | One-way alerts for session events (Stop, Task, Notification) | v4.0 |
| Relay | Bidirectional messaging via inbox queue | v4.1 |
| Memory | Persistent cross-session memory with SQLite + TF-IDF search | v4.2 |
| Proactive | Scheduled briefings, digests, and smart check-ins | v4.3 |

All features beyond core notifications are **off by default** and config-gated. Each layer adds zero runtime dependencies — everything uses Python stdlib.

---

## Quick Start

### 1. Create a Telegram Bot

1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the **bot token**
2. Send any message to your new bot to create the chat
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find `"chat":{"id":NNNNNN}` — that's your **chat ID**

### 2. Set Credentials

Add to your shell profile (`~/.zshrc` or `~/.bashrc`):

```bash
export HOOKLINE_BOT_TOKEN="123456:ABCdefGHIjklMNOpqrSTUvwxYZ"
export HOOKLINE_CHAT_ID="987654321"
```

Legacy env vars (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) are also supported — hookline reads both, with `HOOKLINE_*` taking precedence.

### 3. Install

```bash
git clone https://github.com/Mathews-Tom/hookline.git
cd hookline
pip install -e .
```

### 4. Configure Claude Code Hooks

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [{ "type": "command", "command": "python3 -m hookline" }],
    "Notification": [{ "type": "command", "command": "python3 -m hookline" }],
    "SubagentStop": [{ "type": "command", "command": "python3 -m hookline" }],
    "TaskCompleted": [{ "type": "command", "command": "python3 -m hookline" }],
    "TeammateIdle": [{ "type": "command", "command": "python3 -m hookline" }],
    "PreToolUse": [{ "type": "command", "command": "python3 -m hookline" }]
  }
}
```

### 5. Verify

```bash
hookline health
hookline on
echo '{"hook_event_name":"Stop","cwd":"/test/demo"}' | python3 -m hookline --dry-run
hookline off
```

---

## CLI

```
hookline <command> [args] [--project NAME] [--dry-run]

commands:
  on       enable notifications (global or --project scoped)
  off      disable notifications
  status   show enabled state, daemon, relay, memory, scheduler status
  serve    start Telegram polling daemon
  health   run self-diagnostics
  doctor   extended diagnostics
  reset    clear thread/tasks/debounce state
  config   print effective configuration
  migrate  migrate from notify to hookline
  version  print version

flags:
  --project NAME  scope on/off/reset to a specific project
  --dry-run       process hooks without sending messages
```

Notifications are **OFF by default**. Enable per-project when starting long runs:

```bash
hookline on                  # Enable for project (from cwd name)
hookline on myproject        # Enable for specific project
hookline on --project all    # Enable globally
hookline off                 # Disable
hookline status              # Show what's enabled
hookline reset               # Clear thread state between tasks
```

---

## Notification Messages

**Full events** (Stop, TaskCompleted, Notification) get box-drawing headers and transcript summaries:

```
┌─ ✅ Stop ─────── 🔮 pramana
│ Team disbanded. The report covers architecture,
│ every feature's working status, security issues…
│ 🔧 47 tool calls: 12 Bash, 9 Read, 8 Edit, 6 Grep, 5 Glob
└─ 18:52 UTC ── ⏱ 42m
```

**Debounced events** (SubagentStop, TeammateIdle) batch into compact one-liners:

```
📋 ×4 subagents finished · 🔮 pramana · 18:10–18:52 UTC
💤 challenger, researcher-1 idle · 🔮 pramana · 18:50 UTC
```

**Inline buttons** appear on every notification:

```
[🔇 Mute 30m]  [🔇 Mute Project]
[📌 New Thread]
```

All messages in a session are **threaded** under the first notification — keeps Telegram chat clean.

---

## Serve Daemon

The serve daemon handles button presses, reply commands, relay messaging, and scheduled tasks. Start it:

```bash
hookline serve
```

Or run as a background service:

**macOS (launchd):**
```bash
launchctl load ~/Library/LaunchAgents/com.hookline.serve.plist
```

**Linux (systemd):**
```bash
systemctl --user start hookline-serve
```

The daemon uses Telegram long-polling (outbound-only, no open ports).

---

## Reply Commands

Reply to any notification in Telegram with these commands:

### Transcript Queries

| Command | Output |
|---------|--------|
| `log` / `details` | Last 3 assistant messages with tool summary |
| `full` | Upload transcript tail as `.txt` document |
| `errors` | Extract and send only error blocks |
| `tools` | Bar chart of all tool calls by type |
| `help` | List all available commands |

### Relay Commands

Requires `relay_enabled: true` in config.

| Command | Action |
|---------|--------|
| `send <text>` | Queue a message to the active session's inbox |
| `pause` | Pause the session (blocks next PreToolUse) |
| `resume` | Resume a paused session |
| `sessions` | List active sessions with projects |
| `inbox` | Show unread inbox messages |
| `clear` | Clear all inbox messages |

### Memory Commands

Requires `memory_enabled: true` in config.

| Command | Action |
|---------|--------|
| `remember <text>` | Store a fact or note in project memory |
| `recall <query>` | Search memory by text similarity |
| `goals` | List active goals for the project |
| `context` | Show memory context snapshot |
| `forget <id>` | Deactivate a memory entry by ID |

### Schedule Commands

Requires `schedule_enabled: true` in config.

| Command | Action |
|---------|--------|
| `schedule` | Show scheduled task status and last-run times |
| `digest` | Trigger a manual daily digest |
| `briefing` | Trigger a manual morning briefing |

---

## Bidirectional Relay

Enable with `relay_enabled: true`. The relay provides Telegram → Claude Code messaging via a filesystem inbox queue.

### How It Works

```
Telegram User
    │ sends message (reply to notification thread)
    v
hookline serve (long-poll daemon)
    │ writes to inbox queue
    v
~/.claude/hookline-state/{project}/relay/inbox.jsonl
    ^
    │ hook reads inbox on each event
Claude Code Session
```

No new processes. No open ports. Filesystem IPC via JSONL with `fcntl` locking.

### Free-Standing Messages

Messages sent to the bot outside of a thread are routed based on active sessions:

- **One active session**: auto-queued to that session
- **Multiple sessions**: prompts you to reply to a specific thread or use `send <msg>`
- **No sessions**: ignored

### Pause / Resume

`pause` writes a signal file that blocks the next `PreToolUse` hook until `resume` is sent. This lets you halt Claude Code from Telegram without killing the session.

---

## Memory System

Enable with `memory_enabled: true`. Provides persistent cross-session memory using SQLite (stdlib `sqlite3`) with pure-Python TF-IDF search.

### Storage

Database: `~/.claude/hookline-state/memory.db` (configurable via `memory_db_path`)

Two tables:
- **messages** — conversation history (project, sender, text, timestamp, intent, tags)
- **knowledge** — structured entries (facts, goals, preferences) with active/inactive state

### Intent Tags

Include tags in Telegram messages for structured memory:

| Tag | Effect |
|-----|--------|
| `[REMEMBER] always use ruff for linting` | Stores as a knowledge fact |
| `[GOAL] ship v2.0 by Friday` | Creates an active goal |
| `[DONE] ship v2.0` | Marks matching goal as completed |

Tags are parsed and stripped before display. Hashtags (`#deploy`, `#bug`) are also extracted and stored.

### Search

`recall <query>` uses a two-layer search:
1. SQL `LIKE` for exact substring matches
2. TF-IDF cosine similarity for semantic ranking

Expected scale: ~100 messages/day. Pure-Python search completes in <100ms at this volume.

---

## Proactive Features

Enable with `schedule_enabled: true`. All proactive features run inside the serve daemon loop — no additional processes.

### Morning Briefing

Scheduled summary of active goals, running sessions, and pending approvals.

Default schedule: weekdays at 9:00 AM UTC (`0 9 * * 1-5`).

### Daily Digest

End-of-day summary of session activity, memory stats, and goal progress.

Default schedule: daily at 6:00 PM UTC (`0 18 * * *`).

### Smart Check-in

Periodic evaluation that only sends when there's actionable information — unread inbox messages, paused sessions, active goals. Fires silently if nothing is noteworthy.

Default: disabled (`checkin_interval: 0`). Set to minutes between check-ins.

### Scheduler

Cron-like engine supporting 5-field expressions (`minute hour day-of-month month day-of-week`) with wildcards, ranges, steps, and lists. Also supports fixed intervals via `interval_minutes`. State persists across daemon restarts.

---

## Tool Approval

Enable with `approval_enabled: true`. Claude Code pauses before running a tool, sends an approval request to Telegram with inline buttons, and blocks until you respond or the timeout expires.

```
┌─ 🔐 Approval Required ─────── 🔮 pramana
│ Tool: Bash
│ rm -rf /tmp/build-artifacts
│ Session: 12m active
└─ ⏳ Waiting (120s timeout)

[✅ Approve]  [❌ Block]
```

Auto-blocks on timeout. Configure `approval_timeout` (default 120s) and `approval_user` to restrict who can approve.

---

## Configuration

Settings file: `~/.claude/hookline.json`

Three-tier precedence: **env var → config file → default**.

### Full Configuration Reference

```json
{
  "show_buttons": true,
  "debounce_window": 30,
  "suppress": [],
  "min_session_age": 0,

  "approval_enabled": false,
  "approval_user": "",
  "approval_timeout": 120,

  "relay_enabled": false,
  "relay_mode": "inbox",

  "memory_enabled": false,
  "memory_db_path": "",
  "memory_max_entries": 10000,

  "schedule_enabled": false,
  "briefing_cron": "0 9 * * 1-5",
  "digest_cron": "0 18 * * *",
  "checkin_interval": 0
}
```

### Settings Reference

| Setting | Config Key | Env Override | Default |
|---------|-----------|-------------|---------|
| Show inline buttons | `show_buttons` | `HOOKLINE_BUTTONS` | `true` |
| Debounce window (seconds) | `debounce_window` | `HOOKLINE_DEBOUNCE` | `30` |
| Suppressed events | `suppress` | `HOOKLINE_SUPPRESS` | `[]` |
| Min session age (seconds) | `min_session_age` | `HOOKLINE_MIN_AGE` | `0` |
| Enable tool approval | `approval_enabled` | `HOOKLINE_APPROVAL` | `false` |
| Authorized approval user | `approval_user` | `HOOKLINE_APPROVAL_USER` | chat ID |
| Approval timeout (seconds) | `approval_timeout` | `HOOKLINE_APPROVAL_TIMEOUT` | `120` |
| Enable relay | `relay_enabled` | `HOOKLINE_RELAY` | `false` |
| Relay mode | `relay_mode` | `HOOKLINE_RELAY_MODE` | `inbox` |
| Enable memory | `memory_enabled` | `HOOKLINE_MEMORY` | `false` |
| Memory database path | `memory_db_path` | `HOOKLINE_MEMORY_DB` | `(auto)` |
| Max memory entries | `memory_max_entries` | `HOOKLINE_MEMORY_MAX` | `10000` |
| Enable scheduler | `schedule_enabled` | `HOOKLINE_SCHEDULE` | `false` |
| Briefing schedule | `briefing_cron` | `HOOKLINE_BRIEFING_CRON` | `0 9 * * 1-5` |
| Digest schedule | `digest_cron` | `HOOKLINE_DIGEST_CRON` | `0 18 * * *` |
| Check-in interval (minutes) | `checkin_interval` | `HOOKLINE_CHECKIN_INTERVAL` | `0` |

### Credentials

| Variable | Description |
|----------|-------------|
| `HOOKLINE_BOT_TOKEN` | Bot token from @BotFather |
| `HOOKLINE_CHAT_ID` | Your Telegram chat ID |

Legacy: `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are also read (hookline vars take precedence).

### Project Emojis

Configure per-project emojis in `~/.claude/hookline-projects.json`:

```json
{
  "myapp": "🚀",
  "tests": "🧪",
  "infra": "🔧"
}
```

Messages show the emoji next to the project name for quick visual scanning.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Claude Code                           │
│   Agent (Lead)  ·  Teammate  ·  Teammate                 │
│       │              │              │                    │
│  ─────┴──────────────┴──────────────┴──────────────────  │
│       Hook Events (deterministic, always fire)           │
└───────┼──────────────┼──────────────┼────────────────────┘
        ▼              ▼              ▼
   ┌──────────────────────────────────────────────────┐
   │              hookline package                    │
   │                                                  │
   │  Layer 0: Hook Path (zero deps, sub-ms exit)     │
   │  ├─ Sentinel gate → event filter → debounce     │
   │  ├─ Format (HTML + box drawing)                  │
   │  ├─ Send (threaded, with buttons)                │
   │  └─ Check inbox → surface unread messages        │
   │                                                  │
   │  Layer 1: Serve Daemon (long-poll)               │
   │  ├─ Button callbacks (mute, thread reset)        │
   │  ├─ Reply commands (log, full, errors, tools)    │
   │  ├─ Relay routing (send, pause, resume)          │
   │  ├─ Memory commands (remember, recall, goals)    │
   │  ├─ Schedule commands (schedule, digest, brief)  │
   │  └─ scheduler.tick() → proactive handlers        │
   │                                                  │
   │  Layer 2: Relay (filesystem IPC)                 │
   │  └─ inbox.jsonl ← write_inbox / read_inbox       │
   │                                                  │
   │  Layer 3: Memory (sqlite3 stdlib)                │
   │  ├─ Message store + knowledge base               │
   │  ├─ TF-IDF search (pure Python)                  │
   │  └─ Intent tags ([REMEMBER], [GOAL], [DONE])     │
   │                                                  │
   │  Layer 4: Proactive (scheduler)                  │
   │  ├─ Morning briefing (goals, sessions)           │
   │  ├─ Daily digest (activity stats)                │
   │  └─ Smart check-in (actionable items only)       │
   └──────────────────┬───────────────────────────────┘
                      ▼
              Telegram Bot API (outbound-only)
                      │
              ┌───────┴────────┐
              ▼                ▼
         Your Phone     Serve Daemon
                        (long-poll)
```

### Dependency Model

| Layer | Scope | Dependencies |
|-------|-------|-------------|
| Layer 0 | Hook path (event handler) | Zero — stdlib only |
| Layer 1 | Serve daemon (polling, buttons, replies) | Zero — stdlib only |
| Layer 2 | Relay (inbox queue) | Zero — JSON + file I/O |
| Layer 3 | Memory (store + search) | Zero — sqlite3 + math (stdlib) |
| Layer 4 | Proactive (scheduler + handlers) | Zero — datetime (stdlib) |

### Network Model

Outbound-only. No open ports, no webhooks, no gateway. Telegram Bot API long-polling for all communication. Filesystem IPC for relay (JSONL) and approval (named pipes).

### Package Structure

```
hookline/
├── __init__.py          # v4.3.0, re-exports public API
├── __main__.py          # Hook event handler (stdin dispatch)
├── cli.py               # Unified CLI (on/off/status/serve/health/config/...)
├── config.py            # Paths, credentials, settings (3-tier precedence)
├── _log.py              # Logging with RotatingFileHandler
├── _types.py            # TypedDicts for all state structures
├── state.py             # Atomic JSON CRUD with fcntl locking
├── session.py           # Sentinel detection, age, duration, mute
├── project.py           # Project emoji config, labels
├── formatting.py        # HTML formatting, box drawing, escaping
├── debounce.py          # Event batching (accumulate/flush)
├── tasks.py             # TaskCompleted counter per session
├── threads.py           # Thread ID lifecycle (get/set/clear/find)
├── buttons.py           # Inline keyboard building
├── telegram.py          # Telegram Bot API transport (urllib)
├── replies.py           # Transcript query handlers
├── approval.py          # Tool approval flow (FIFO pipes, audit log)
├── serve.py             # Long-poll daemon (buttons, replies, relay, scheduler)
├── commands.py          # Extensible command registry (@register decorator)
├── relay.py             # Inbox queue (write/read/mark_read/pause/resume)
├── migrate.py           # Migration from notify → hookline
├── scheduler.py         # Cron-like task scheduler engine
├── proactive.py         # Briefing, digest, check-in handlers
└── memory/
    ├── __init__.py      # Memory subsystem package
    ├── store.py         # SQLite message + knowledge store
    ├── search.py        # TF-IDF vectorizer + cosine similarity
    ├── intents.py       # Intent tag parser ([REMEMBER], [GOAL], [DONE])
    └── knowledge.py     # Knowledge base manager
```

### State Files

```
~/.claude/
├── hookline-enabled                    # Global sentinel (ON/OFF)
├── hookline-enabled.{project}          # Per-project sentinel
├── hookline.json                       # User preferences
├── hookline-projects.json              # Project emoji mapping
├── hookline-state/
│   ├── serve.pid                       # Daemon PID
│   ├── serve.log                       # Rotating daemon log (5 MB × 3)
│   ├── audit.jsonl                     # Tool approval audit log
│   ├── scheduler.json                  # Scheduler last-run timestamps
│   ├── memory.db                       # SQLite memory store
│   └── {project}/
│       ├── thread.json                 # Thread message ID
│       ├── tasks.json                  # Task progress counter
│       ├── debounce.json               # Pending batched events
│       ├── mute.json                   # Mute-until timestamp
│       ├── approval.json               # Pending approval state
│       └── relay/
│           ├── session.json            # Active session info
│           ├── inbox.jsonl             # Message queue
│           └── paused                  # Pause signal file
```

---

## Migration from notify

If upgrading from `claude-notify` (v3.x):

```bash
hookline migrate
```

This copies state, config, and sentinels from `notify-*` paths to `hookline-*` paths, and updates `~/.claude/settings.json` hook commands from `python3 -m notify` to `python3 -m hookline`.

---

## Development

### Test Suite

196 tests across 11 test modules:

```bash
uv run pytest tests/ -v
```

| Module | Coverage |
|--------|----------|
| `test_config.py` | Config precedence, validation |
| `test_state.py` | JSON CRUD, locking, atomic writes |
| `test_session.py` | Sentinel detection, age, duration, mute |
| `test_formatting.py` | HTML escaping, box drawing, format_full/compact |
| `test_transcript.py` | JSONL parsing, summary extraction, mtime cache |
| `test_debounce.py` | Event accumulation, flush timing |
| `test_main.py` | Integration event routing, dry-run |
| `test_commands.py` | Command registry, dispatch |
| `test_relay.py` | Inbox queue, pause/resume, sessions |
| `test_memory.py` | SQLite store, TF-IDF search, intents, knowledge |
| `test_proactive.py` | Cron parsing, scheduler tick, proactive handlers |

### Linting and Type Checking

```bash
uv run ruff check hookline/
uv run pyright hookline/
```

### Dry Run

Process events without Telegram calls:

```bash
echo '{"hook_event_name":"Stop","cwd":"/test/demo"}' | hookline --dry-run
```

---

## Why Hooks

| Approach | Mechanism | Guarantee |
|----------|-----------|-----------|
| Skill | Instructions Claude reads → must *remember* to notify | Probabilistic |
| MCP Server | Tool Claude can call → must *decide* to notify | Probabilistic |
| **Hook** | Shell command fired by runtime on lifecycle events | **Deterministic** |

Hooks fire on every lifecycle event. hookline decides whether to send based on sentinels, mute state, suppression rules, and debounce windows.

## License

MIT
