# Claude Code → Telegram Notifications

**Rich Telegram alerts for Claude Code sessions — debouncing, threading, project emojis, inline controls, transcript queries, and tool approval.**

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

Every notification includes inline buttons handled by the serve daemon (auto-started via launchd):

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

## Architecture

```text
┌──────────────────────────────────────────────────┐
│                  Claude Code                     │
│   Agent (Lead)  ·  Teammate  ·  Teammate         │
│       │              │              │            │
│  ─────┴──────────────┴──────────────┴──────────  │
│       Hook Events (deterministic, always fire)   │
└───────┼──────────┼──────────────────┼────────────┘
        ▼          ▼                  ▼
   ┌───────────────────────────────────────────┐
   │              notify.py                    │
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
   Your Phone    Thread Group     notify.py --serve
                                 (launchd daemon)
                                       │
                         ┌─────────────┼─────────────┐
                         ▼             ▼             ▼
                    [🔇 Mute]   [📌 Thread]   Reply Commands
                                              (log, full, errors, tools)
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
│   ├── audit.jsonl                 # Tool approval audit log
│   └── pramana/
│       ├── debounce.json           # Pending batched events
│       ├── thread.json             # First message_id for threading
│       ├── tasks.json              # Completed task tracker
│       └── mute.json               # Mute-until timestamp
├── hooks/
│   ├── notify.py                   # Hook handler + serve daemon
│   └── toggle.sh                   # On/off/reset/status toggle
└── commands/
    └── notify.md                   # /notify slash command
```

---

## Setup

### Prerequisites
- Python 3.10+ (stdlib only, zero dependencies)
- A Telegram account

### 1. Create a Telegram Bot
1. Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → copy the **bot token**
2. Message your new bot (send anything to create the chat)
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
4. Find `"chat":{"id":NNNNNN}` — that's your **chat ID**

### 2. Run Setup

```bash
git clone <this-repo> && cd claude-telegram-hooks
./setup.sh
# Or non-interactive:
./setup.sh --token "YOUR_BOT_TOKEN" --chat "YOUR_CHAT_ID"
```

Installs:

- `~/.claude/hooks/notify.py` — hook handler + serve daemon
- `~/.claude/hooks/toggle.sh` — on/off/reset/status toggle
- `~/.claude/commands/notify.md` — `/notify` slash command
- `~/.claude/notify-config.json` — notification preferences
- `~/.claude/notify-projects.json` — project emoji config
- `~/.claude/notify-state/` — state directory
- Hook config → `~/.claude/settings.json`
- Credentials + aliases → `~/.zshrc`
- Serve daemon → `~/Library/LaunchAgents/com.claude.notify-serve.plist` (auto-start)

### 3. Verify
```bash
source ~/.zshrc
notify-on
echo '{"hook_event_name":"Stop","cwd":"/test/pramana"}' | python3 ~/.claude/hooks/notify.py
# → Telegram message: ┌─ ✅ Stop ─────── pramana
notify-off
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

### Uninstall

```bash
./setup.sh --uninstall
```

Removes all installed components. Preserves `notify-projects.json` (user config).

---

## Serve Daemon

The serve daemon handles inline button presses, transcript reply commands, and tool approval callbacks. It is **auto-installed via launchd** during setup and starts on login.

```bash
# Manual start (if not using launchd)
python3 ~/.claude/hooks/notify.py --serve

# Check status
/notify status
# → 🟢 Serve daemon: running (PID 12345)
```

Logs: `~/.claude/notify-state/serve.{stdout,stderr}.log`

---

## Why Hooks, Not a Skill or MCP

| Approach | How It Works | Guarantee |
|----------|-------------|-----------|
| **Skill** | Instructions Claude reads → must *remember* to notify | "Probably" |
| **MCP Server** | Tool Claude can call → must *decide* to notify | "Probably" |
| **Hook** | Shell command fired by runtime on lifecycle events | **"Always"** |

Hooks fire deterministically. The toggle, debounce, and mute logic all happen inside `notify.py` — the hook always fires, the script decides whether to send.

## Zero Dependencies

Python stdlib only: `json`, `urllib`, `sys`, `os`, `pathlib`, `time`, `fcntl`, `select`. No pip install, no venvs, no version conflicts.

## License

MIT
