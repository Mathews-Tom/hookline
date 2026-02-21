#!/usr/bin/env bash
# setup.sh — Install Claude Code Telegram notification hooks
#
# Usage:
#   ./setup.sh                     # Interactive: prompts for bot token + chat ID
#   ./setup.sh --token XXX --chat YYY  # Non-interactive
#   ./setup.sh --update            # Re-run setup, reuse existing credentials
#   ./setup.sh --uninstall         # Remove all installed components
#
# What it does:
#   1. Copies notify/ package to ~/.claude/hooks/
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
UNINSTALL=false
UPDATE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token)     TOKEN="$2"; shift 2 ;;
        --chat)      CHAT="$2";  shift 2 ;;
        --uninstall) UNINSTALL=true; shift ;;
        --update)    UPDATE=true; shift ;;
        *)           echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Uninstall mode ──────────────────────────────────────────────────────────

if [[ "$UNINSTALL" == "true" ]]; then
    echo "──────────────────────────────────────────────"
    echo "  Uninstalling Claude Code Telegram Hooks"
    echo "──────────────────────────────────────────────"
    echo ""

    # Remove hook scripts and package
    if [[ -d "$HOME/.claude/hooks/notify" ]]; then
        rm -rf "$HOME/.claude/hooks/notify"
        echo "  Removed $HOME/.claude/hooks/notify/"
    fi
    # Legacy monolith cleanup
    if [[ -f "$HOME/.claude/hooks/notify.py" ]]; then
        rm -f "$HOME/.claude/hooks/notify.py"
        echo "  Removed $HOME/.claude/hooks/notify.py"
    fi
    if [[ -f "$HOME/.claude/hooks/toggle.sh" ]]; then
        rm -f "$HOME/.claude/hooks/toggle.sh"
        echo "  Removed $HOME/.claude/hooks/toggle.sh"
    fi

    # Remove slash command
    if [[ -f "$HOME/.claude/commands/notify.md" ]]; then
        rm -f "$HOME/.claude/commands/notify.md"
        echo "  Removed ~/.claude/commands/notify.md"
    fi

    # Remove hooks from settings.json
    if [[ -f "$SETTINGS_FILE" ]]; then
        python3 - "$SETTINGS_FILE" << 'PYEOF'
import json
import sys

settings_path = sys.argv[1]
with open(settings_path) as f:
    settings = json.load(f)

hooks = settings.get("hooks", {})
changed = False
for event in list(hooks.keys()):
    matchers = hooks[event]
    filtered = []
    for matcher in matchers:
        hook_list = matcher.get("hooks", [])
        hook_list = [h for h in hook_list if "hooks/notify" not in h.get("command", "")]
        if hook_list:
            matcher["hooks"] = hook_list
            filtered.append(matcher)
    if filtered:
        hooks[event] = filtered
    else:
        del hooks[event]
        changed = True

if hooks:
    settings["hooks"] = hooks
elif "hooks" in settings:
    del settings["hooks"]

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
print("  Cleaned notify hooks from settings.json")
PYEOF
    fi

    # Remove env vars and aliases from shell profile
    PROFILE=""
    if [[ -f "$HOME/.zshrc" ]]; then
        PROFILE="$HOME/.zshrc"
    elif [[ -f "$HOME/.bashrc" ]]; then
        PROFILE="$HOME/.bashrc"
    elif [[ -f "$HOME/.bash_profile" ]]; then
        PROFILE="$HOME/.bash_profile"
    fi

    if [[ -n "$PROFILE" ]]; then
        grep -v "TELEGRAM_BOT_TOKEN\|TELEGRAM_CHAT_ID\|# Claude Code Telegram\|alias notify-on\|alias notify-off\|alias notify-status" "$PROFILE" > "$PROFILE.tmp" || true
        mv "$PROFILE.tmp" "$PROFILE"
        echo "  Cleaned env vars and aliases from $PROFILE"
    fi

    # Remove daemon (OS-specific)
    PLIST="$HOME/Library/LaunchAgents/com.claude.notify-serve.plist"
    if [[ -f "$PLIST" ]]; then
        launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
        echo "  Removed launchd agent (com.claude.notify-serve)"
    fi
    SERVICE="$HOME/.config/systemd/user/claude-notify-serve.service"
    if [[ -f "$SERVICE" ]]; then
        systemctl --user stop claude-notify-serve.service 2>/dev/null || true
        systemctl --user disable claude-notify-serve.service 2>/dev/null || true
        rm -f "$SERVICE"
        systemctl --user daemon-reload 2>/dev/null || true
        echo "  Removed systemd service (claude-notify-serve)"
    fi

    # Remove config file
    if [[ -f "$HOME/.claude/notify-config.json" ]]; then
        rm -f "$HOME/.claude/notify-config.json"
        echo "  Removed ~/.claude/notify-config.json"
    fi

    # Remove state directory
    if [[ -d "$HOME/.claude/notify-state" ]]; then
        rm -rf "$HOME/.claude/notify-state"
        echo "  Removed ~/.claude/notify-state/"
    fi

    # Remove sentinel files
    rm -f "$HOME/.claude/notify-enabled"
    rm -f "$HOME/.claude/notify-enabled".*
    echo "  Removed sentinel files"

    echo ""
    echo "  Note: ~/.claude/notify-projects.json preserved (user config)"
    echo ""
    echo "──────────────────────────────────────────────"
    echo "  Uninstall complete."
    echo "  Restart your shell or run: source $PROFILE"
    echo "──────────────────────────────────────────────"
    exit 0
fi

# ── Extract existing credentials (--update mode) ──────────────────────────

if [[ "$UPDATE" == "true" && ( -z "$TOKEN" || -z "$CHAT" ) ]]; then
    _extract_from_profile() {
        local profile="$1"
        [[ -f "$profile" ]] || return 0
        if [[ -z "$TOKEN" ]]; then
            TOKEN=$(sed -n 's/^export TELEGRAM_BOT_TOKEN="\(.*\)"/\1/p' "$profile" 2>/dev/null | head -1)
        fi
        if [[ -z "$CHAT" ]]; then
            CHAT=$(sed -n 's/^export TELEGRAM_CHAT_ID="\(.*\)"/\1/p' "$profile" 2>/dev/null | head -1)
        fi
    }

    # 1. Shell profiles
    _extract_from_profile "$HOME/.zshrc"
    _extract_from_profile "$HOME/.bashrc"
    _extract_from_profile "$HOME/.bash_profile"

    # 2. Installed launchd plist
    _PLIST="$HOME/Library/LaunchAgents/com.claude.notify-serve.plist"
    if [[ -f "$_PLIST" ]]; then
        if [[ -z "$TOKEN" ]]; then
            TOKEN=$(sed -n '/TELEGRAM_BOT_TOKEN/{n;s/.*<string>\(.*\)<\/string>.*/\1/p;}' "$_PLIST" 2>/dev/null | head -1)
        fi
        if [[ -z "$CHAT" ]]; then
            CHAT=$(sed -n '/TELEGRAM_CHAT_ID/{n;s/.*<string>\(.*\)<\/string>.*/\1/p;}' "$_PLIST" 2>/dev/null | head -1)
        fi
    fi

    # 3. Current environment
    if [[ -z "$TOKEN" ]]; then TOKEN="${TELEGRAM_BOT_TOKEN:-}"; fi
    if [[ -z "$CHAT" ]]; then CHAT="${TELEGRAM_CHAT_ID:-}"; fi

    # Report what we found
    if [[ -n "$TOKEN" && -n "$CHAT" ]]; then
        _masked_token="${TOKEN%%:*}:${TOKEN#*:}"
        _after_colon="${_masked_token#*:}"
        _masked_token="${_masked_token%%:*}:${_after_colon:0:3}***"
        echo "→ Reusing existing Telegram credentials"
        echo "  Token: $_masked_token"
        echo "  Chat:  $CHAT"
    fi
fi

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
echo "→ Installing notify package to $HOOKS_DIR/"
mkdir -p "$HOOKS_DIR"
# Remove legacy monolith if present
rm -f "$HOOKS_DIR/notify.py"
# Copy package directory
rm -rf "$HOOKS_DIR/notify"
cp -r "$SCRIPT_DIR/notify" "$HOOKS_DIR/notify"
VERSION=$(PYTHONPATH="$HOOKS_DIR" python3 -m notify --version 2>/dev/null || echo "unknown")
echo "  Installed $VERSION"

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

# ── Install notification config (if not already present) ─────────────────────

CONFIG_FILE="$HOME/.claude/notify-config.json"
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "→ Installing default notification config"
    cat > "$CONFIG_FILE" << 'JSONEOF'
{
  "show_buttons": true,
  "debounce_window": 30,
  "suppress": [],
  "min_session_age": 0,
  "approval_enabled": false,
  "approval_user": "",
  "approval_timeout": 120
}
JSONEOF
    echo "  Edit $CONFIG_FILE to customize settings"
else
    echo "→ Config already exists at $CONFIG_FILE (skipping)"
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
# Also migrate legacy notify.py commands to the notify package path
existing_hooks = settings.get("hooks", {})
migrated = 0

# First pass: migrate any legacy "hooks/notify.py" → "hooks/notify" in existing hooks
for event in list(existing_hooks.keys()):
    for matcher in existing_hooks[event]:
        for hook in matcher.get("hooks", []):
            cmd = hook.get("command", "")
            if "hooks/notify.py" in cmd or (cmd.endswith("hooks/notify") and "PYTHONPATH" not in cmd):
                hook["command"] = "PYTHONPATH=~/.claude/hooks python3 -m notify"
                migrated += 1

# Second pass: add new hook events that don't already exist
for event, matchers in new_hooks["hooks"].items():
    if event not in existing_hooks:
        existing_hooks[event] = matchers
    else:
        existing_cmds = {
            h.get("command", "")
            for m in existing_hooks[event]
            for h in m.get("hooks", [])
        }
        # Check for notify hook (either old or new command format)
        if not any("notify" in cmd and ("hooks/notify" in cmd or "-m notify" in cmd) for cmd in existing_cmds):
            existing_hooks[event].extend(matchers)

settings["hooks"] = existing_hooks

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)

if migrated:
    print(f"  Migrated {migrated} legacy notify.py hooks → notify package")
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
    grep -v "TELEGRAM_BOT_TOKEN\|TELEGRAM_CHAT_ID\|# Claude Code Telegram\|alias notify-on\|alias notify-off\|alias notify-status" "$PROFILE" > "$PROFILE.tmp" || true
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
    TELEGRAM_BOT_TOKEN="$TOKEN" TELEGRAM_CHAT_ID="$CHAT" PYTHONPATH="$HOOKS_DIR" python3 -m notify 2>&1) || true

# Remove sentinel — notifications start OFF by default
rm -f "$SENTINEL"

if echo "$TEST_RESULT" | grep -q "Sent"; then
    echo "  ✓ Test notification sent! Check Telegram."
else
    echo "  ✗ Test failed. Output: $TEST_RESULT"
    echo "    Verify your bot token and chat ID are correct."
    exit 1
fi

# ── Install serve daemon (OS-specific) ───────────────────────────────────

OS="$(uname -s)"
echo ""

if [[ "$OS" == "Darwin" ]]; then
    PLIST_SRC="$SCRIPT_DIR/com.claude.notify-serve.plist"
    PLIST_DST="$HOME/Library/LaunchAgents/com.claude.notify-serve.plist"

    echo "→ Installing serve daemon (launchd)"
    mkdir -p "$HOME/Library/LaunchAgents"

    sed -e "s|__HOOKS_DIR__|$HOOKS_DIR|g" \
        -e "s|__BOT_TOKEN__|$TOKEN|g" \
        -e "s|__CHAT_ID__|$CHAT|g" \
        -e "s|__HOME__|$HOME|g" \
        "$PLIST_SRC" > "$PLIST_DST"

    launchctl unload "$PLIST_DST" 2>/dev/null || true
    if launchctl load "$PLIST_DST" 2>/dev/null; then
        echo "  Installed and started com.claude.notify-serve"
    else
        echo "  ⚠ launchctl load failed — start manually: launchctl load $PLIST_DST"
    fi
    echo "  Logs: ~/.claude/notify-state/serve.{stdout,stderr}.log"

elif [[ "$OS" == "Linux" ]]; then
    SYSTEMD_DIR="$HOME/.config/systemd/user"
    SERVICE_SRC="$SCRIPT_DIR/claude-notify-serve.service"
    SERVICE_DST="$SYSTEMD_DIR/claude-notify-serve.service"

    echo "→ Installing serve daemon (systemd user service)"
    mkdir -p "$SYSTEMD_DIR"

    sed -e "s|__HOOKS_DIR__|$HOOKS_DIR|g" \
        -e "s|__BOT_TOKEN__|$TOKEN|g" \
        -e "s|__CHAT_ID__|$CHAT|g" \
        "$SERVICE_SRC" > "$SERVICE_DST"

    systemctl --user daemon-reload
    systemctl --user enable claude-notify-serve.service
    systemctl --user restart claude-notify-serve.service
    echo "  Installed and started claude-notify-serve.service"
    echo "  Check: systemctl --user status claude-notify-serve"
    echo "  Logs:  journalctl --user -u claude-notify-serve -f"

else
    echo "→ Skipping daemon install (unsupported OS: $OS)"
    echo "  Run manually: PYTHONPATH=~/.claude/hooks python3 -m notify --serve"
fi

echo ""
echo "──────────────────────────────────────────────"
echo "  Setup complete!"
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
echo "  Settings:"
echo "    Edit ~/.claude/notify-config.json"
echo "    (buttons, debounce, suppress, approval — env vars override)"
echo ""
echo "  Project emojis:"
echo "    Edit ~/.claude/notify-projects.json"
echo ""
echo "  Serve daemon (auto-started via launchd):"
echo "    Handles mute buttons, reply commands, tool approval"
echo "    Reply to any notification with: log, full, errors, tools"
echo ""
echo "  Restart your shell or run: source $PROFILE"
echo "──────────────────────────────────────────────"
