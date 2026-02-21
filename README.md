# Claude Code → Telegram Notifications

**Rich Telegram alerts for Claude Code sessions — debouncing, threading, project emojis, inline controls, transcript queries, and tool approval.**

`claude-notify v3.1.0` — stdlib-only Python package, zero runtime dependencies.

Notifications are **OFF by default**. Toggle on per-project when starting long runs, toggle off when done.

## What Messages Look Like

**Full events** (Stop, TaskCompleted, Notification) get box-drawing headers + blockquote body:

```
┌─ ✅ Stop ─────── 🔮 pramana
│ Team disbanded. The report covers architecture,
│ every feature's working status, security issues…
│ 🔧 47 tool calls: 12 Bash, 9 Read, 8 Edit, 6 Grep, 5 Glob
└─ 18:52 UTC ── ⏱ 42m
```

```
┌─ 🎯 TaskCompleted ─────── 🧪 attest
│ Task 3/6
│ After researchers A, B, C report: stress-test
│ their conclusions. Look for unstated assumptions…
└─ 18:49 UTC ── ⏱ 39m
```

**Debounced events** (SubagentStop, TeammateIdle) are batched into compact one-liners:

```
📋 ×4 subagents finished · 🔮 pramana · 18:10–18:52 UTC
💤 challenger, researcher-1 idle · 🔮 pramana · 18:50 UTC
```

**Inline buttons** appear on every notification:

```
[🔇 Mute 30m]  [🔇 Mute Project]
[📌 New Thread]
```

---

## Daily Workflow

```text
You                          Claude Code                    Your Phone
 │                                │                              │
 ├─ /notify on ──────────────────►│                              │
 │  🔔 ON for pramana             │                              │
 │                                │                              │
 ├─ "Create an agent team..."────►│                              │
 │                                ├─ Spawns teammates            │
 │  (you walk away)               ├─ Working...                  │
 │                                ├─ SubagentStop ×3             │
 │                                │  (debounced, silent)         │
 │                                ├─ [Notification fires] ──────►│ ┌─ ⏳ Notification ──── 🔮
 │                                │  (flushes batch first)  ────►│ 📋 ×3 subagents finished
 │                                │                              │
 │                                ├─ TeammateIdle ×2             │
 │                                │  (debounced, silent)         │
 │                                ├─ [TaskCompleted fires] ─────►│ ┌─ 🎯 Task 3/6 ──── 🔮
 │                                │  (flushes batch first)  ────►│ 💤 challenger, researcher idle
 │                                │                              │
 │  (you come back)               │                              │
 │                                ├─ [Stop fires] ──────────────►│ ┌─ ✅ Stop ──── 🔮
 │                                │                              │   ⏱ 42m session
 │                                │                              │
 ├─ /notify reset ───────────────►│  (start new thread)          │
 ├─ "New task..."────────────────►│                              │
 │                                ├─ [Notification fires] ──────►│ ┌─ ⏳ New thread ──── 🔮
 │                                │                              │
 ├─ /notify off ─────────────────►│                              │
 │  🔕 OFF for pramana            │                              │
```

All messages in a session are **threaded under the first message** — keeps your Telegram chat clean. Use `/notify reset` or the `📌 New Thread` button between task runs to start a fresh thread.

### Toggle from Any Interface

```text
~/.claude/notify-enabled.{project}   ← project-scoped
~/.claude/notify-enabled             ← global fallback
```

**Claude Code CLI / App / CoWork** — `/notify` slash command:

```text
/notify on              Enable for current project (from cwd)
/notify on all          Enable for all projects
/notify on attest       Enable for attest specifically
/notify off             Disable current project
/notify off all         Clear everything
/notify reset           Start a new thread (between task runs)
/notify reset all       Reset threads for all projects
/notify status          Show what's enabled
```

**Shell aliases** (instant, no LLM turn):

```bash
notify-on               # Project from cwd
notify-off
notify-status
```

---

## Features

### HTML Formatting with Box Drawing
Full events use `<blockquote>` for indented body text and Unicode box-drawing for visual weight. Stop events include transcript summaries — last assistant messages, tool call counts, and detected errors.

### Project Emoji Mapping

Configure per-project emojis in `~/.claude/notify-projects.json`:

```json
{
  "attest": "🧪",
  "cairn": "🪨",
  "swarmlens": "🔭",
  "pramana": "🔮"
}
```
Messages show `🔮 pramana` instead of plain `pramana`. Scannable at a glance when multiple projects are active.

### Session Duration

The footer shows elapsed time since you toggled notifications on:

```text
└─ 18:52 UTC ── ⏱ 42m
```

Reads the timestamp from the sentinel file — zero additional state.

### Debouncing

SubagentStop and TeammateIdle events are batched within a configurable window (default 30s). Instead of 4 separate "Subagent finished" messages:

```text
📋 ×4 subagents finished · 🔮 pramana · 18:10–18:52 UTC
```

Batches flush when: a non-debounced event arrives, the batch ages past the window, or the session ends (Stop).

### Task Progress

TaskCompleted events track cumulative progress per session:

```text
┌─ 🎯 TaskCompleted ─────── 🧪 attest
│ Task 3/6
│ Stress-test conclusions. Look for unstated assumptions…
└─ 18:49 UTC ── ⏱ 39m
```

Counter resets on Stop or thread reset.

### Thread Grouping

All messages from a session are threaded under the first message via Telegram's `reply_to_message_id`. One thread per task run instead of scattered messages.

Use `/notify reset` (CLI) or `📌 New Thread` (Telegram button) between task runs within the same session to start a new thread. This clears thread state, task counters, and pending debounce batches.

### Inline Buttons

Every notification includes inline buttons handled by the serve daemon:

| Button | Action |
|--------|--------|
| `🔇 Mute 30m` | Suppress notifications for 30 minutes |
| `🔇 Mute Project` | Disable the project sentinel entirely |
| `📌 New Thread` | Clear thread state — next notification starts a new thread |

Buttons are **on by default**. Disable via config: `"show_buttons": false`.

### Transcript Queries

Reply to any notification in Telegram with a command to query the session transcript:

| Command | Output |
|---------|--------|
| `log` / `details` | Last 3 assistant messages with tool summary |
| `full` | Upload transcript tail as `.txt` document |
| `errors` | Extract and send only error blocks |
| `tools` | Bar chart of all tool calls by type |
| `help` | List available commands |

### Tool Approval (Opt-in)

PreToolUse hook integration: Claude Code pauses before running a tool, sends an approval request to Telegram with inline `✅ Approve` / `❌ Block` buttons, and blocks until you respond or the timeout expires.

```text
┌─ 🔐 Approval Required ─────── 🔮 pramana
│ Tool: Bash
│ rm -rf /tmp/build-artifacts
│ Session: 12m active
└─ ⏳ Waiting (120s timeout)
```

Auto-blocks on timeout. Enable via config: `"approval_enabled": true`.

### Event Suppression

Suppress specific events so they never trigger notifications:

```json
{ "suppress": ["SubagentStop", "TeammateIdle"] }
```

Or via env var: `CLAUDE_NOTIFY_SUPPRESS="SubagentStop,TeammateIdle"`

### Minimum Session Age

Ignore notifications from sessions younger than a threshold. Prevents alerts from quick one-off commands:

```json
{ "min_session_age": 60 }
```

Notifications only fire after the session has been active for 60+ seconds.

---

## CLI Flags

The `notify` package supports several CLI flags for development and diagnostics:

```bash
python3 -m notify --version     # Print version (claude-notify 3.1.0)
python3 -m notify --dry-run     # Format + print to stdout, no Telegram calls
python3 -m notify --health      # Run self-diagnostics (7 checks)
python3 -m notify --serve       # Start the serve daemon (blocking)
```

### Health Check

`--health` validates your setup in one command:

```text
claude-notify v3.1.0 health check
=============================================
  [+] BOT_TOKEN        OK    7123456:***
  [+] CHAT_ID          OK    123456789
  [+] Bot valid        OK    @my_notify_bot
  [+] Chat reachable   OK    OK
  [+] State dir        OK    /home/user/.claude/notify-state
  [+] State files      OK    all valid
  [-] Serve daemon     FAIL  not running
=============================================
  Status: ISSUES DETECTED
```

Also available via toggle: `toggle.sh doctor`

### Dry Run

`--dry-run` processes events and prints formatted HTML to stdout without making any Telegram API calls. Bypasses the sentinel gate so notifications don't need to be enabled:

```bash
echo '{"hook_event_name":"Stop","cwd":"/test/demo"}' | python3 -m notify --dry-run
```

---

## Architecture

```text
┌──────────────────────────────────────────────────┐
│                  Claude Code                     │
│   Agent (Lead)  ·  Teammate  ·  Teammate         │
│       │              │              │            │
│  ─────┴──────────────┴──────────────┴──────────  │
│       Hook Events (deterministic, always fire)   │
└───────┼──────────────┼──────────────┼────────────┘
        ▼              ▼              ▼
   ┌───────────────────────────────────────────┐
   │            notify/ package                │
   │                                           │
   │  1. Read event from stdin                 │
   │  2. Sentinel gate: project or global?     │
   │     └─ No sentinel → exit (sub-ms)        │
   │  3. Mute check: button-muted?             │
   │     └─ Muted → exit                       │
   │  4. Suppress check: event filtered?       │
   │     └─ Suppressed → exit                  │
   │  5. Session age check                     │
   │  6. Debounce: SubagentStop/TeammateIdle?  │
   │     └─ Accumulate → exit (don't send yet) │
   │  7. Flush stale batches                   │
   │  8. Format: HTML + box drawing            │
   │  9. Send: thread grouping + buttons       │
   │ 10. Stop? Clean up session state          │
   └──────────────────┬────────────────────────┘
                      ▼
              Telegram Bot API
                      │
        ┌─────────────┼──────────────────────┐
        ▼             ▼                      ▼
   Your Phone    Thread Group     python3 -m notify --serve
                                 (launchd / systemd daemon)
                                       │
                         ┌─────────────┼─────────────┐
                         ▼             ▼             ▼
                    [🔇 Mute]   [📌 Thread]   Reply Commands
                                              (log, full, errors, tools)
```

### Package Structure

```text
notify/
├── __init__.py        # v3.1.0, re-exports public API
├── __main__.py        # CLI dispatch (--version, --health, --dry-run, --serve)
├── _log.py            # Logging with RotatingFileHandler for serve daemon
├── _types.py          # TypedDicts for all state files
├── config.py          # Paths, credentials, _load_config, constants
├── state.py           # Atomic JSON CRUD with fcntl locking
├── session.py         # Sentinel detection, age, duration, mute, enabled
├── project.py         # Project emoji config, labels
├── transcript.py      # JSONL parsing with mtime-based cache
├── formatting.py      # HTML formatting, box drawing, _esc, _truncate
├── debounce.py        # Event batching (accumulate, flush, should_flush)
├── tasks.py           # TaskCompleted counter per session
├── threads.py         # Thread ID lifecycle (get/set/clear/find)
├── buttons.py         # Inline keyboard building, last-button state
├── telegram.py        # Telegram Bot API transport, send_message
├── replies.py         # Reply command handlers (log, full, errors, tools)
├── approval.py        # Tool approval flow (FIFO pipes, audit logging)
└── serve.py           # Long-poll daemon for buttons, replies, approvals
```

### Configuration

Settings are read with three-tier precedence: **env var → config file → hardcoded default**.

Credentials (secrets) are always env vars. Preferences live in `~/.claude/notify-config.json`:

```json
{
  "show_buttons": true,
  "debounce_window": 30,
  "suppress": [],
  "min_session_age": 0,
  "approval_enabled": false,
  "approval_user": "",
  "approval_timeout": 120
}
```

| Setting | Config Key | Env Override | Default |
|---------|-----------|-------------|---------|
| Show inline buttons | `show_buttons` | `CLAUDE_NOTIFY_BUTTONS=1/0` | `true` |
| Debounce window (seconds) | `debounce_window` | `CLAUDE_NOTIFY_DEBOUNCE` | `30` |
| Suppressed events | `suppress` | `CLAUDE_NOTIFY_SUPPRESS` | `[]` |
| Min session age (seconds) | `min_session_age` | `CLAUDE_NOTIFY_MIN_AGE` | `0` |
| Enable tool approval | `approval_enabled` | `CLAUDE_NOTIFY_APPROVAL=1/0` | `false` |
| Authorized approval user | `approval_user` | `CLAUDE_NOTIFY_APPROVAL_USER` | chat ID |
| Approval timeout (seconds) | `approval_timeout` | `CLAUDE_NOTIFY_APPROVAL_TIMEOUT` | `120` |

Credentials (required, env vars only):

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |

### State Files

```text
~/.claude/
├── notify-enabled.pramana          # Sentinel: ON for pramana
├── notify-config.json              # User preferences (buttons, debounce, etc.)
├── notify-projects.json            # Project emoji mapping
├── notify-state/
│   ├── serve.pid                   # Daemon PID file
│   ├── serve.log                   # Rotating daemon log (5MB × 3 backups)
│   ├── audit.jsonl                 # Tool approval audit log
│   └── pramana/
│       ├── debounce.json           # Pending batched events
│       ├── thread.json             # First message_id for threading
│       ├── tasks.json              # Completed task tracker
│       └── mute.json               # Mute-until timestamp
├── hooks/
│   ├── notify/                     # Hook handler package (17 modules)
│   └── toggle.sh                   # On/off/reset/status toggle
└── commands/
    └── notify.md                   # /notify slash command
```

---

## Setup

### Prerequisites
- Python 3.10+ (stdlib only, zero runtime dependencies)
- A Telegram account
- macOS (launchd) or Linux (systemd) for the serve daemon

### 1. Create a Telegram Bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the **bot token**
2. Message your new bot (send anything to create the chat)
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find `"chat":{"id":NNNNNN}` — that's your **chat ID**

### 2. Run Setup

```bash
git clone <this-repo> && cd claude-hooks-telegram
./setup.sh
# Or non-interactive:
./setup.sh --token "YOUR_BOT_TOKEN" --chat "YOUR_CHAT_ID"
```

Installs:

- `~/.claude/hooks/notify/` — hook handler package
- `~/.claude/hooks/toggle.sh` — on/off/reset/status toggle
- `~/.claude/commands/notify.md` — `/notify` slash command
- `~/.claude/notify-config.json` — notification preferences
- `~/.claude/notify-projects.json` — project emoji config
- `~/.claude/notify-state/` — state directory
- Hook config → `~/.claude/settings.json`
- Credentials + aliases → `~/.zshrc`
- Serve daemon:
  - **macOS** → `~/Library/LaunchAgents/com.claude.notify-serve.plist` (auto-start on login)
  - **Linux** → `~/.config/systemd/user/claude-notify-serve.service` (auto-start on login)

### 3. Verify
```bash
source ~/.zshrc
notify-on
echo '{"hook_event_name":"Stop","cwd":"/test/pramana"}' | python3 ~/.claude/hooks/notify
# → Telegram message: ┌─ ✅ Stop ─────── pramana
notify-off
```

Run diagnostics:
```bash
python3 -m notify --health
# Or via toggle:
toggle.sh doctor
```

### 4. Customize

**Project emojis** — `~/.claude/notify-projects.json`:
```json
{
  "attest": "🧪",
  "cairn": "🪨",
  "pramana": "🔮"
}
```

**Notification preferences** — `~/.claude/notify-config.json`:
```json
{
  "show_buttons": true,
  "debounce_window": 30,
  "suppress": ["SubagentStop"],
  "min_session_age": 60
}
```

### Update

Re-run setup to update the package while keeping existing credentials:

```bash
./setup.sh --update
```

### Uninstall

```bash
./setup.sh --uninstall
```

Removes all installed components (hooks, daemon, state, env vars). Preserves `notify-projects.json` (user config).

---

## Serve Daemon

The serve daemon handles inline button presses, transcript reply commands, and tool approval callbacks. It is **auto-installed during setup** and starts on login.

**macOS** — managed via launchd:
```bash
launchctl list com.claude.notify-serve       # Check status
launchctl unload ~/Library/LaunchAgents/com.claude.notify-serve.plist  # Stop
launchctl load ~/Library/LaunchAgents/com.claude.notify-serve.plist    # Start
```

**Linux** — managed via systemd user service:
```bash
systemctl --user status claude-notify-serve   # Check status
systemctl --user stop claude-notify-serve     # Stop
systemctl --user start claude-notify-serve    # Start
journalctl --user -u claude-notify-serve -f   # Follow logs
```

**Manual start** (any OS):
```bash
python3 -m notify --serve
# Or: python3 ~/.claude/hooks/notify --serve
```

Logs rotate automatically: `~/.claude/notify-state/serve.log` (5 MB, 3 backups).

---

## Development

### Test Suite

88 tests across 7 test modules, running in ~0.1s:

```bash
make test
# Or: python3 -m pytest tests/ -v
```

Test modules:
- `test_config.py` — config precedence (`_cfg_bool`, `_cfg_int`, `_cfg_str`, `_cfg_suppress`)
- `test_state.py` — JSON CRUD, locking, atomic writes
- `test_session.py` — sentinel detection, age, duration, mute, enabled
- `test_formatting.py` — `_esc`, `_truncate`, `_strip_html`, `format_full`, `format_compact`
- `test_transcript.py` — JSONL parsing, summary extraction, mtime caching
- `test_debounce.py` — accumulate, flush, timing
- `test_main.py` — integration event routing, dry-run, version

### Makefile Targets

```bash
make test       # Run pytest
make lint       # Ruff check
make typecheck  # Pyright
make format     # Ruff format
make dry-run    # Format a Stop event to stdout
make health     # Run self-diagnostics
make install    # Re-install via setup.sh --update
```

---

## Why Hooks, Not a Skill or MCP

| Approach | How It Works | Guarantee |
|----------|-------------|-----------|
| **Skill** | Instructions Claude reads → must *remember* to notify | "Probably" |
| **MCP Server** | Tool Claude can call → must *decide* to notify | "Probably" |
| **Hook** | Shell command fired by runtime on lifecycle events | **"Always"** |

Hooks fire deterministically. The toggle, debounce, and mute logic all happen inside the `notify` package — the hook always fires, the package decides whether to send.

## Zero Dependencies

Python stdlib only: `json`, `urllib`, `sys`, `os`, `pathlib`, `time`, `fcntl`, `select`, `logging`, `errno`, `re`, `uuid`. No pip install, no venvs, no version conflicts.

Dev dependencies (tests only): `pytest`.

## License

MIT
