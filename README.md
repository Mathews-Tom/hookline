# Claude Code → Telegram Notifications

**Rich Telegram alerts for Claude Code Agent Teams with debouncing, threading, project emojis, and inline mute buttons.**

Notifications are **OFF by default**. Toggle on per-project when starting long runs, toggle off when done.

## What Messages Look Like

**Full events** (Stop, TaskCompleted, Notification) get box-drawing headers + blockquote body:

```
┌─ ✅ Stop ─────── 🔮 pramana
│ Team disbanded. The report covers architecture,
│ every feature's working status, security issues…
└─ 18:52 UTC ── ⏱ 42m
```

```
┌─ 🎯 TaskCompleted ─────── 🧪 attest
│ Task 3/6
│ After researchers A, B, C report: stress-test
│ their conclusions. Look for unstated assumptions…
└─ 18:49 UTC ── ⏱ 39m
```

**Debounced events** (SubagentStop, TeammateIdle) are batched into compact single-liners:

```
📋 ×4 subagents finished · 🔮 pramana · 18:10–18:52 UTC
💤 challenger, researcher-1 idle · 🔮 pramana · 18:50 UTC
```

**Before vs After**:

| Before (v1) | After (v2) |
|---|---|
| 8 separate flat messages in 2 minutes | 4 messages: 1 batched + 3 full events |
| No visual hierarchy | Box drawing for important events |
| "SubagentStop · pramana" ×4 | "×4 subagents finished" once |
| No duration info | ⏱ 42m session timer |
| Plain project name | 🔮 project emoji |
| Scattered in chat | Threaded under first message |

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
 ├─ /notify off ─────────────────►│                              │
 │  🔕 OFF for pramana            │                              │
```

All messages in a session are **threaded under the first message** — keeps your Telegram chat clean.

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

### 1. HTML Formatting with Box Drawing
Full events use `<blockquote>` for indented body text and Unicode box-drawing for visual weight. Switched from MarkdownV2 to HTML for richer formatting options.

### 2. Project Emoji Mapping

Configure per-project emojis in `~/.claude/notify-projects.json`:

```json
{
  "attest": "🧪",
  "cairn": "🪨",
  "swarmlens": "🔭",
  "no-magic": "✨",
  "tether": "🔗",
  "pramana": "🔮"
}
```
Messages show `🔮 pramana` instead of plain `pramana`. Scannable at a glance when multiple projects are active.

### 3. Session Duration

The footer shows elapsed time since you toggled notifications on:

```text
└─ 18:52 UTC ── ⏱ 42m
```

Reads the timestamp from the sentinel file — zero additional state.

### 4. Debouncing

SubagentStop and TeammateIdle events are batched within a 30-second window. Instead of 4 separate "Subagent finished" messages, you get one:

```text
📋 ×4 subagents finished · 🔮 pramana · 18:10–18:52 UTC
```

Batches flush when: a non-debounced event arrives, the batch ages past the window, or the session ends (Stop).

Configure the window: `export CLAUDE_NOTIFY_DEBOUNCE=60` (default: 30 seconds)

### 5. Compact Mode

Low-value events (TeammateIdle when standalone) get single-line format. High-value events (Stop, TaskCompleted, Notification) get the full box-drawing treatment.

### 6. Task Progress

TaskCompleted events track cumulative progress per session:

```text
┌─ 🎯 TaskCompleted ─────── 🧪 attest
│ Task 3/6
│ Stress-test conclusions. Look for unstated assumptions…
└─ 18:49 UTC ── ⏱ 39m
```

Counter resets when the session ends (Stop event).

### 7. Thread Grouping

All messages from a session are threaded under the first message via Telegram's `reply_to_message_id`. Keeps your chat clean — one thread per Agent Team run instead of scattered messages.

### 8. Inline Mute Buttons
Messages include `[🔇 Mute 30m]` and `[🔇 Mute Project]` buttons. Requires the optional button server:
```bash
export CLAUDE_NOTIFY_BUTTONS=1
python3 ~/.claude/hooks/notify.py --serve &
```
The server long-polls Telegram for button presses and handles mute state.

### 9. Event Suppression

Suppress specific events: `export CLAUDE_NOTIFY_SUPPRESS="SubagentStop,TeammateIdle"`

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
   │  4. Debounce: SubagentStop/TeammateIdle?  │
   │     └─ Accumulate → exit (don't send yet) │
   │  5. Flush stale batches                   │
   │  6. Format: HTML + box drawing            │
   │  7. Send: thread grouping + buttons       │
   │  8. Stop? Clean up session state          │
   └──────────────────┬────────────────────────┘
                      ▼
              Telegram Bot API
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   Your Phone    Thread Group   [🔇 Mute]
                                    │
                              notify.py --serve
                             (button callback handler)
```

### State Files

```text
~/.claude/
├── notify-enabled.pramana          # Sentinel: ON for pramana
├── notify-projects.json            # Emoji mapping
├── notify-state/
│   └── pramana/
│       ├── debounce.json           # Pending batched events
│       ├── thread.json             # First message_id for threading
│       ├── tasks.json              # Completed task tracker
│       └── mute.json               # Mute-until timestamp
└── hooks/
    ├── notify.py                   # Hook handler (753 lines)
    └── toggle.sh                   # On/off/status toggle
```

---

## Setup (5 minutes)

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

- `~/.claude/hooks/notify.py` — hook handler
- `~/.claude/hooks/toggle.sh` — on/off/status toggle
- `~/.claude/commands/notify.md` — `/notify` slash command
- `~/.claude/notify-projects.json` — project emoji config
- `~/.claude/notify-state/` — state directory
- Hook config → `~/.claude/settings.json`
- Shell aliases → `~/.zshrc`

### 3. Verify
```bash
source ~/.zshrc
notify-on
echo '{"hook_event_name":"Stop","cwd":"/test/pramana"}' | python3 ~/.claude/hooks/notify.py
# → Telegram message: ┌─ ✅ Stop ─────── pramana
notify-off
```

### 4. Customize Project Emojis

```bash
# Edit ~/.claude/notify-projects.json
{
  "attest": "🧪",
  "cairn": "🪨",
  "pramana": "🔮"
}
```

### 5. Enable Inline Buttons (Optional)

```bash
# Add to ~/.zshrc
export CLAUDE_NOTIFY_BUTTONS=1

# Start the button server (background)
python3 ~/.claude/hooks/notify.py --serve &

# Or use launchd (macOS) for auto-start — see below
```

---

## Button Server (Optional)

The button server handles inline mute button presses. Without it, notifications work fine — you just won't see the mute buttons.

### Quick Start

```bash
export CLAUDE_NOTIFY_BUTTONS=1
python3 ~/.claude/hooks/notify.py --serve
# [notify-serve] Button server started. Polling for callbacks...
```

### launchd Auto-Start (macOS)

Create `~/Library/LaunchAgents/com.claude.notify-serve.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.claude.notify-serve</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>${HOME}/.claude/hooks/notify.py</string>
        <string>--serve</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TELEGRAM_BOT_TOKEN</key>
        <string>YOUR_TOKEN</string>
        <key>TELEGRAM_CHAT_ID</key>
        <string>YOUR_CHAT_ID</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.claude.notify-serve.plist
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Bot token from @BotFather (required) |
| `TELEGRAM_CHAT_ID` | — | Your chat ID (required) |
| `CLAUDE_NOTIFY_SUPPRESS` | — | Comma-separated events to suppress |
| `CLAUDE_NOTIFY_MIN_AGE` | `0` | Min session age (seconds) before notifying |
| `CLAUDE_NOTIFY_BUTTONS` | `0` | Set to `1` to show inline mute buttons |
| `CLAUDE_NOTIFY_DEBOUNCE` | `30` | Debounce window in seconds |

---

## Why Hooks, Not a Skill or MCP

| Approach | How It Works | Guarantee |
|----------|-------------|-----------|
| **Skill** | Instructions Claude reads → must *remember* to notify | "Probably" |
| **MCP Server** | Tool Claude can call → must *decide* to notify | "Probably" |
| **Hook** | Shell command fired by runtime on lifecycle events | **"Always"** |

Hooks fire deterministically. The toggle, debounce, and mute logic all happen inside `notify.py` — the hook always fires, the script decides whether to send.

## Zero Dependencies

Python stdlib only: `json`, `urllib`, `sys`, `os`, `pathlib`, `time`, `re`. No pip install, no venvs, no version conflicts.

## License

MIT
