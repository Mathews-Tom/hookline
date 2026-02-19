#!/usr/bin/env bash
# setup.sh — Install Claude Code Telegram notification hooks
#
# Usage:
#   ./setup.sh                     # Interactive: prompts for bot token + chat ID
#   ./setup.sh --token XXX --chat YYY  # Non-interactive
#
# What it does:
#   1. Copies notify.py to ~/.claude/hooks/
#   2. Merges hook config into ~/.claude/settings.json
#   3. Adds TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to shell profile
#   4. Sends a test notification
#
set -euo pipefail

HOOKS_DIR="$HOME/.claude/hooks"
SETTINGS_FILE="$HOME/.claude/settings.json"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Parse args ───────────────────────────────────────────────────────────────

TOKEN=""
CHAT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token) TOKEN="$2"; shift 2 ;;
        --chat)  CHAT="$2";  shift 2 ;;
        *)       echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Interactive prompts if needed ────────────────────────────────────────────

if [[ -z "$TOKEN" ]]; then
    echo "──────────────────────────────────────────────"
    echo "  Claude Code → Telegram Notification Setup"
    echo "──────────────────────────────────────────────"
    echo ""
    echo "You'll need a Telegram bot token and your chat ID."
    echo "  1. Message @BotFather on Telegram → /newbot → copy the token"
    echo "  2. Message your new bot, then visit:"
    echo "     https://api.telegram.org/bot<TOKEN>/getUpdates"
    echo "     Look for \"chat\":{\"id\":NNNNNN} — that's your chat ID"
    echo ""
    read -rp "Bot token: " TOKEN
fi

if [[ -z "$CHAT" ]]; then
    read -rp "Chat ID:   " CHAT
fi

if [[ -z "$TOKEN" || -z "$CHAT" ]]; then
    echo "Error: Both token and chat ID are required."
    exit 1
fi

# ── Install notify.py ────────────────────────────────────────────────────────

echo ""
echo "→ Installing notify.py to $HOOKS_DIR/"
mkdir -p "$HOOKS_DIR"
cp "$SCRIPT_DIR/notify.py" "$HOOKS_DIR/notify.py"
chmod +x "$HOOKS_DIR/notify.py"

# ── Install toggle.sh ────────────────────────────────────────────────────────

echo "→ Installing toggle.sh to $HOOKS_DIR/"
cp "$SCRIPT_DIR/toggle.sh" "$HOOKS_DIR/toggle.sh"
chmod +x "$HOOKS_DIR/toggle.sh"

# ── Install slash command ────────────────────────────────────────────────────

COMMANDS_DIR="$HOME/.claude/commands"
echo "→ Installing /notify slash command to $COMMANDS_DIR/"
mkdir -p "$COMMANDS_DIR"
cp "$SCRIPT_DIR/notify.md" "$COMMANDS_DIR/notify.md"

# ── Install project config (if not already present) ─────────────────────────

PROJECT_CONFIG="$HOME/.claude/notify-projects.json"
if [[ ! -f "$PROJECT_CONFIG" ]]; then
    echo "→ Installing default project emoji config"
    cp "$SCRIPT_DIR/notify-projects.json" "$PROJECT_CONFIG"
    echo "  Edit $PROJECT_CONFIG to customize project emojis"
else
    echo "→ Project config already exists at $PROJECT_CONFIG (skipping)"
fi

# ── Create state directory ───────────────────────────────────────────────────

mkdir -p "$HOME/.claude/notify-state"

# ── Merge hooks into settings.json ───────────────────────────────────────────

echo "→ Configuring hooks in $SETTINGS_FILE"
mkdir -p "$(dirname "$SETTINGS_FILE")"

if [[ ! -f "$SETTINGS_FILE" ]]; then
    echo '{}' > "$SETTINGS_FILE"
fi

# Use Python to safely merge the hooks config (jq not guaranteed on macOS)
python3 - "$SETTINGS_FILE" "$SCRIPT_DIR/hooks.json" << 'PYEOF'
import json
import sys

settings_path = sys.argv[1]
hooks_path = sys.argv[2]

with open(settings_path) as f:
    settings = json.load(f)

with open(hooks_path) as f:
    new_hooks = json.load(f)

# Merge hooks — append to existing hook events, don't overwrite
existing_hooks = settings.get("hooks", {})
for event, matchers in new_hooks["hooks"].items():
    if event not in existing_hooks:
        existing_hooks[event] = matchers
    else:
        # Check if we already have the notify.py hook for this event
        existing_cmds = {
            h.get("command", "")
            for m in existing_hooks[event]
            for h in m.get("hooks", [])
        }
        if "python3 ~/.claude/hooks/notify.py" not in existing_cmds:
            existing_hooks[event].extend(matchers)

settings["hooks"] = existing_hooks

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)

print(f"  Updated {len(new_hooks['hooks'])} hook events")
PYEOF

# ── Set environment variables ────────────────────────────────────────────────

echo "→ Setting environment variables"

# Detect shell profile
PROFILE=""
if [[ -f "$HOME/.zshrc" ]]; then
    PROFILE="$HOME/.zshrc"
elif [[ -f "$HOME/.bashrc" ]]; then
    PROFILE="$HOME/.bashrc"
elif [[ -f "$HOME/.bash_profile" ]]; then
    PROFILE="$HOME/.bash_profile"
fi

if [[ -n "$PROFILE" ]]; then
    # Remove any existing entries
    grep -v "TELEGRAM_BOT_TOKEN\|TELEGRAM_CHAT_ID\|# Claude Code Telegram" "$PROFILE" > "$PROFILE.tmp" || true
    mv "$PROFILE.tmp" "$PROFILE"

    # Append new entries
    cat >> "$PROFILE" << EOF

# Claude Code Telegram notifications
export TELEGRAM_BOT_TOKEN="$TOKEN"
export TELEGRAM_CHAT_ID="$CHAT"
alias notify-on="bash ~/.claude/hooks/toggle.sh on"
alias notify-off="bash ~/.claude/hooks/toggle.sh off"
alias notify-status="bash ~/.claude/hooks/toggle.sh status"
EOF

    echo "  Added to $PROFILE"
else
    echo "  ⚠ Could not detect shell profile. Add manually:"
    echo "    export TELEGRAM_BOT_TOKEN=\"$TOKEN\""
    echo "    export TELEGRAM_CHAT_ID=\"$CHAT\""
fi

# Export for current session
export TELEGRAM_BOT_TOKEN="$TOKEN"
export TELEGRAM_CHAT_ID="$CHAT"

# ── Test notification ────────────────────────────────────────────────────────

echo ""
echo "→ Sending test notification..."

# Temporarily enable notifications for the test
SENTINEL="$HOME/.claude/notify-enabled"
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$SENTINEL"

TEST_RESULT=$(echo '{"hook_event_name": "Stop", "cwd": "/test/claude-telegram-hooks", "stop_hook_active": false}' | \
    TELEGRAM_BOT_TOKEN="$TOKEN" TELEGRAM_CHAT_ID="$CHAT" python3 "$HOOKS_DIR/notify.py" 2>&1)

# Remove sentinel — notifications start OFF by default
rm -f "$SENTINEL"

if echo "$TEST_RESULT" | grep -q "Sent"; then
    echo "  ✓ Test notification sent! Check Telegram."
else
    echo "  ✗ Test failed. Output: $TEST_RESULT"
    echo "    Verify your bot token and chat ID are correct."
    exit 1
fi

echo ""
echo "──────────────────────────────────────────────"
echo "  ✅ Setup complete!"
echo ""
echo "  Notifications are OFF by default."
echo "  Toggle them when starting long runs:"
echo ""
echo "    Claude Code (CLI / App / CoWork):"
echo "      /notify on          Enable for current project"
echo "      /notify on all      Enable for all projects"
echo "      /notify off         Disable for current project"
echo "      /notify off all     Disable all notifications"
echo "      /notify status      Show what's enabled"
echo ""
echo "    Terminal (instant, no LLM turn):"
echo "      notify-on           Enable for current dir's project"
echo "      notify-off          Disable for current dir's project"
echo "      notify-status       Show all active sentinels"
echo ""
echo "  Project emojis:"
echo "    Edit ~/.claude/notify-projects.json"
echo ""
echo "  Inline mute buttons (optional):"
echo "    export CLAUDE_NOTIFY_BUTTONS=1"
echo "    python3 ~/.claude/hooks/notify.py --serve &"
echo ""
echo "  Restart your shell or run: source $PROFILE"
echo "──────────────────────────────────────────────"
