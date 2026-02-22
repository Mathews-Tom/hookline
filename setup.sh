#!/usr/bin/env bash
# setup.sh — Install Claude Code Telegram notification hooks
#
# Usage:
#   ./setup.sh                     # Interactive: prompts for bot token + chat ID
#   ./setup.sh --token XXX --chat YYY  # Non-interactive
#   ./setup.sh --update            # Re-run setup, reuse existing credentials
#   ./setup.sh --migrate           # Migrate from notify to hookline
#   ./setup.sh --uninstall         # Remove all installed components
#
# What it does:
#   1. Copies hookline/ package to ~/.claude/hooks/
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
MIGRATE=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token)     TOKEN="$2"; shift 2 ;;
        --chat)      CHAT="$2";  shift 2 ;;
        --uninstall) UNINSTALL=true; shift ;;
        --update)    UPDATE=true; shift ;;
        --migrate)   MIGRATE=true; shift ;;
        *)           echo "❌ Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Uninstall mode ──────────────────────────────────────────────────────────

if [[ "$UNINSTALL" == "true" ]]; then
    echo ""
    echo "🗑️  Uninstalling Hookline"
    echo "──────────────────────────────────────────────"
    echo ""

    # Remove hook scripts and packages (both hookline and legacy notify)
    if [[ -d "$HOME/.claude/hooks/hookline" ]]; then
        rm -rf "$HOME/.claude/hooks/hookline"
        echo "  ✅ Removed ~/.claude/hooks/hookline/"
    fi
    if [[ -d "$HOME/.claude/hooks/notify" ]]; then
        rm -rf "$HOME/.claude/hooks/notify"
        echo "  ✅ Removed ~/.claude/hooks/notify/"
    fi
    # Legacy monolith cleanup
    if [[ -f "$HOME/.claude/hooks/notify.py" ]]; then
        rm -f "$HOME/.claude/hooks/notify.py"
        echo "  ✅ Removed ~/.claude/hooks/notify.py"
    fi
    if [[ -f "$HOME/.claude/hooks/toggle.sh" ]]; then
        rm -f "$HOME/.claude/hooks/toggle.sh"
        echo "  ✅ Removed ~/.claude/hooks/toggle.sh"
    fi

    # Remove slash command (both hookline and legacy notify)
    if [[ -f "$HOME/.claude/commands/hookline.md" ]]; then
        rm -f "$HOME/.claude/commands/hookline.md"
        echo "  ✅ Removed ~/.claude/commands/hookline.md"
    fi
    if [[ -f "$HOME/.claude/commands/notify.md" ]]; then
        rm -f "$HOME/.claude/commands/notify.md"
        echo "  ✅ Removed ~/.claude/commands/notify.md"
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
        hook_list = [h for h in hook_list if "hooks/hookline" not in h.get("command", "") and "hooks/notify" not in h.get("command", "")]
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
print("  ✅ Cleaned hookline hooks from settings.json")
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
        grep -v "TELEGRAM_BOT_TOKEN\|TELEGRAM_CHAT_ID\|# Claude Code Telegram\|alias hookline-on\|alias hookline-off\|alias hookline-status\|alias notify-on\|alias notify-off\|alias notify-status" "$PROFILE" > "$PROFILE.tmp" || true
        mv "$PROFILE.tmp" "$PROFILE"
        echo "  ✅ Cleaned env vars and aliases from $PROFILE"
    fi

    # Remove daemon (OS-specific) — both hookline and legacy notify
    PLIST="$HOME/Library/LaunchAgents/com.claude.hookline-serve.plist"
    if [[ -f "$PLIST" ]]; then
        launchctl unload "$PLIST" 2>/dev/null || true
        rm -f "$PLIST"
        echo "  ✅ Removed launchd agent (com.claude.hookline-serve)"
    fi
    PLIST_LEGACY="$HOME/Library/LaunchAgents/com.claude.notify-serve.plist"
    if [[ -f "$PLIST_LEGACY" ]]; then
        launchctl unload "$PLIST_LEGACY" 2>/dev/null || true
        rm -f "$PLIST_LEGACY"
        echo "  ✅ Removed launchd agent (com.claude.notify-serve)"
    fi
    SERVICE="$HOME/.config/systemd/user/claude-hookline-serve.service"
    if [[ -f "$SERVICE" ]]; then
        systemctl --user stop claude-hookline-serve.service 2>/dev/null || true
        systemctl --user disable claude-hookline-serve.service 2>/dev/null || true
        rm -f "$SERVICE"
        systemctl --user daemon-reload 2>/dev/null || true
        echo "  ✅ Removed systemd service (claude-hookline-serve)"
    fi
    SERVICE_LEGACY="$HOME/.config/systemd/user/claude-notify-serve.service"
    if [[ -f "$SERVICE_LEGACY" ]]; then
        systemctl --user stop claude-notify-serve.service 2>/dev/null || true
        systemctl --user disable claude-notify-serve.service 2>/dev/null || true
        rm -f "$SERVICE_LEGACY"
        systemctl --user daemon-reload 2>/dev/null || true
        echo "  ✅ Removed systemd service (claude-notify-serve)"
    fi

    # Remove config file (both hookline and legacy notify)
    if [[ -f "$HOME/.claude/hookline.json" ]]; then
        rm -f "$HOME/.claude/hookline.json"
        echo "  ✅ Removed ~/.claude/hookline.json"
    fi
    if [[ -f "$HOME/.claude/notify-config.json" ]]; then
        rm -f "$HOME/.claude/notify-config.json"
        echo "  ✅ Removed ~/.claude/notify-config.json"
    fi

    # Remove state directories (both hookline and legacy notify)
    if [[ -d "$HOME/.claude/hookline-state" ]]; then
        rm -rf "$HOME/.claude/hookline-state"
        echo "  ✅ Removed ~/.claude/hookline-state/"
    fi
    if [[ -d "$HOME/.claude/notify-state" ]]; then
        rm -rf "$HOME/.claude/notify-state"
        echo "  ✅ Removed ~/.claude/notify-state/"
    fi

    # Remove sentinel files (both hookline and legacy notify)
    rm -f "$HOME/.claude/hookline-enabled"
    rm -f "$HOME/.claude/hookline-enabled".*
    rm -f "$HOME/.claude/notify-enabled"
    rm -f "$HOME/.claude/notify-enabled".*
    echo "  ✅ Removed sentinel files"

    echo ""
    echo "  ℹ️  ~/.claude/hookline.json preserved (user config)"
    echo ""
    echo "──────────────────────────────────────────────"
    echo "✅ Uninstall complete"
    echo "   Restart your shell or run: source $PROFILE"
    echo "──────────────────────────────────────────────"
    exit 0
fi

# ── Migrate mode ─────────────────────────────────────────────────────────────

if [[ "$MIGRATE" == "true" ]]; then
    echo ""
    echo "🔄 Migrating notify → hookline"
    echo "──────────────────────────────────────────────"
    echo ""
    PYTHONPATH="$HOOKS_DIR" python3 -m hookline migrate
    echo ""
    echo "✅ Migration complete — re-run setup.sh to finish installation"
    exit 0
fi

# ── Extract existing credentials (--update mode) ──────────────────────────

if [[ "$UPDATE" == "true" && ( -z "$TOKEN" || -z "$CHAT" ) ]]; then
    _extract_from_env() {
        local envfile="$1"
        [[ -f "$envfile" ]] || return 0
        if [[ -z "$TOKEN" ]]; then
            TOKEN=$(sed -n 's/^HOOKLINE_BOT_TOKEN=\(.*\)/\1/p' "$envfile" 2>/dev/null | head -1)
        fi
        if [[ -z "$CHAT" ]]; then
            CHAT=$(sed -n 's/^HOOKLINE_CHAT_ID=\(.*\)/\1/p' "$envfile" 2>/dev/null | head -1)
        fi
    }

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

    # 1. Project .env (developer's source of truth)
    _extract_from_env "$SCRIPT_DIR/.env"

    # 2. Installed .env (written by previous setup)
    _extract_from_env "$HOOKS_DIR/.env"

    # 3. Shell profiles (legacy)
    _extract_from_profile "$HOME/.zshrc"
    _extract_from_profile "$HOME/.bashrc"
    _extract_from_profile "$HOME/.bash_profile"

    # 4. Installed launchd plist
    _PLIST="$HOME/Library/LaunchAgents/com.claude.hookline-serve.plist"
    if [[ -f "$_PLIST" ]]; then
        if [[ -z "$TOKEN" ]]; then
            TOKEN=$(sed -n '/TELEGRAM_BOT_TOKEN/{n;s/.*<string>\(.*\)<\/string>.*/\1/p;}' "$_PLIST" 2>/dev/null | head -1)
        fi
        if [[ -z "$CHAT" ]]; then
            CHAT=$(sed -n '/TELEGRAM_CHAT_ID/{n;s/.*<string>\(.*\)<\/string>.*/\1/p;}' "$_PLIST" 2>/dev/null | head -1)
        fi
    fi

    # 5. Current environment
    if [[ -z "$TOKEN" ]]; then TOKEN="${TELEGRAM_BOT_TOKEN:-}"; fi
    if [[ -z "$CHAT" ]]; then CHAT="${TELEGRAM_CHAT_ID:-}"; fi

    # Report what we found
    if [[ -n "$TOKEN" && -n "$CHAT" ]]; then
        _masked_token="${TOKEN%%:*}:***${TOKEN: -4}"
        echo "🔑 Reusing existing Telegram credentials"
        echo "   Token: $_masked_token"
        echo "   Chat:  $CHAT"
    fi
fi

# ── Interactive prompts if needed ────────────────────────────────────────────

if [[ -z "$TOKEN" ]]; then
    echo ""
    echo "🎣 Hookline — Telegram Notification Setup"
    echo "──────────────────────────────────────────────"
    echo ""
    echo "  Grab a Telegram bot token and your chat ID:"
    echo ""
    echo "  1️⃣  Message @BotFather → /newbot → copy the token"
    echo "  2️⃣  Open your new bot and send /start"
    echo "     (required before the bot can message you)"
    echo "  3️⃣  Message @userinfobot → it replies with your user ID"
    echo ""
    read -rp "  🔑 Bot token: " TOKEN
fi

if [[ -z "$CHAT" ]]; then
    read -rp "  💬 Chat ID:   " CHAT
fi

if [[ -z "$TOKEN" || -z "$CHAT" ]]; then
    echo "  ❌ Both token and chat ID are required"
    exit 1
fi

# ── Install hookline package ──────────────────────────────────────────────────

echo ""
echo "📦 Installing hookline package"
echo "──────────────────────────────────────────────"
mkdir -p "$HOOKS_DIR"
# Remove legacy monolith and notify package if present
rm -f "$HOOKS_DIR/notify.py"
rm -rf "$HOOKS_DIR/notify"
# Copy hookline package directory
rm -rf "$HOOKS_DIR/hookline"
cp -r "$SCRIPT_DIR/hookline" "$HOOKS_DIR/hookline"
VERSION=$(PYTHONPATH="$HOOKS_DIR" python3 -m hookline --version 2>/dev/null | head -1 || echo "unknown")
echo "  ✅ $VERSION → $HOOKS_DIR/"

# ── Install slash command ────────────────────────────────────────────────────

COMMANDS_DIR="$HOME/.claude/commands"
echo "  ✅ /hookline slash command → $COMMANDS_DIR/"
mkdir -p "$COMMANDS_DIR"
cp "$SCRIPT_DIR/hookline.md" "$COMMANDS_DIR/hookline.md"
# Remove legacy notify slash command if present
rm -f "$COMMANDS_DIR/notify.md"

# ── Install project config (if not already present) ─────────────────────────

PROJECT_CONFIG="$HOME/.claude/hookline-projects.json"
if [[ ! -f "$PROJECT_CONFIG" ]]; then
    # Migrate from legacy notify-projects.json if it exists
    LEGACY_PROJECT_CONFIG="$HOME/.claude/notify-projects.json"
    if [[ -f "$LEGACY_PROJECT_CONFIG" ]]; then
        echo "  🔄 Migrating project emoji config from notify-projects.json"
        cp "$LEGACY_PROJECT_CONFIG" "$PROJECT_CONFIG"
    else
        echo "  ✅ Project emoji config → $PROJECT_CONFIG"
        cp "$SCRIPT_DIR/hookline-projects.json" "$PROJECT_CONFIG"
    fi
else
    echo "  ⏭️  Project config exists (skipping)"
fi

# ── Install notification config (if not already present) ─────────────────────

CONFIG_FILE="$HOME/.claude/hookline.json"
if [[ ! -f "$CONFIG_FILE" ]]; then
    # Migrate from legacy notify-config.json if it exists
    LEGACY_CONFIG_FILE="$HOME/.claude/notify-config.json"
    if [[ -f "$LEGACY_CONFIG_FILE" ]]; then
        echo "  🔄 Migrating notification config from notify-config.json"
        cp "$LEGACY_CONFIG_FILE" "$CONFIG_FILE"
    else
        echo "  ✅ Notification config → $CONFIG_FILE"
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
    fi
else
    echo "  ⏭️  Notification config exists (skipping)"
fi

# ── Create state directory ───────────────────────────────────────────────────

mkdir -p "$HOME/.claude/hookline-state"

# ── Merge hooks into settings.json ───────────────────────────────────────────

echo ""
echo "⚙️  Configuring hooks"
echo "──────────────────────────────────────────────"
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
# Also migrate legacy notify.py and notify package commands to hookline
existing_hooks = settings.get("hooks", {})
migrated = 0

# First pass: migrate any legacy notify commands → hookline package path
for event in list(existing_hooks.keys()):
    for matcher in existing_hooks[event]:
        for hook in matcher.get("hooks", []):
            cmd = hook.get("command", "")
            if "hooks/notify.py" in cmd or "-m notify" in cmd or ("hooks/notify" in cmd and "hookline" not in cmd):
                hook["command"] = "PYTHONPATH=~/.claude/hooks python3 -m hookline"
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
        # Check for hookline hook (either old notify or new hookline command format)
        if not any("hookline" in cmd and "hooks/hookline" in cmd or "-m hookline" in cmd for cmd in existing_cmds):
            existing_hooks[event].extend(matchers)

settings["hooks"] = existing_hooks

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)

if migrated:
    print(f"  🔄 Migrated {migrated} legacy notify hook(s)")
print(f"  ✅ {len(new_hooks['hooks'])} hook events → settings.json")
PYEOF

# ── Write credentials to .env ────────────────────────────────────────────────

echo "  ✅ Credentials → $HOOKS_DIR/.env"

cat > "$HOOKS_DIR/.env" << EOF
# Hookline Telegram credentials (written by setup.sh)
HOOKLINE_BOT_TOKEN=$TOKEN
HOOKLINE_CHAT_ID=$CHAT
EOF

# ── Set shell aliases ────────────────────────────────────────────────────────

echo ""
echo "🐚 Shell aliases"
echo "──────────────────────────────────────────────"

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
    # Remove any existing entries (both hookline and legacy notify aliases/exports)
    grep -v "TELEGRAM_BOT_TOKEN\|TELEGRAM_CHAT_ID\|HOOKLINE_BOT_TOKEN\|HOOKLINE_CHAT_ID\|# Claude Code Telegram\|# hookline (Claude Code\|alias hookline-on\|alias hookline-off\|alias hookline-status\|alias notify-on\|alias notify-off\|alias notify-status" "$PROFILE" > "$PROFILE.tmp" || true
    mv "$PROFILE.tmp" "$PROFILE"

    # Append aliases only (no credentials in shell profile)
    cat >> "$PROFILE" << 'EOF'

# Claude Code Telegram notifications
alias hookline-on="python3 -m hookline on"
alias hookline-off="python3 -m hookline off"
alias hookline-status="python3 -m hookline status"
EOF

    echo "  ✅ Added hookline-{on,off,status} to $PROFILE"
else
    echo "  ⚠️  Could not detect shell profile"
fi

# Export for current session (test notification needs these)
export HOOKLINE_BOT_TOKEN="$TOKEN"
export HOOKLINE_CHAT_ID="$CHAT"

# ── Test notification ────────────────────────────────────────────────────────

echo ""
echo "🧪 Test notification"
echo "──────────────────────────────────────────────"

# Temporarily enable notifications for the test
SENTINEL="$HOME/.claude/hookline-enabled"
date -u '+%Y-%m-%dT%H:%M:%SZ' > "$SENTINEL"

TEST_RESULT=$(echo '{"hook_event_name": "Stop", "cwd": "/test/claude-telegram-hooks", "stop_hook_active": false}' | \
    HOOKLINE_BOT_TOKEN="$TOKEN" HOOKLINE_CHAT_ID="$CHAT" PYTHONPATH="$HOOKS_DIR" python3 -m hookline 2>&1) || true

# Remove sentinel — notifications start OFF by default
rm -f "$SENTINEL"

if echo "$TEST_RESULT" | grep -q "Sent"; then
    echo "  ✅ Test notification sent — check Telegram"
else
    echo "  ❌ Test failed"
    echo "     Output: $TEST_RESULT"
    echo ""
    echo "  Troubleshoot:"
    echo "  • Verify your bot token and chat ID"
    echo "  • Send /start to your bot first"
    echo "    (Telegram blocks bot messages until you do)"
    exit 1
fi

# ── Install serve daemon (OS-specific) ───────────────────────────────────

OS="$(uname -s)"
echo ""
echo "🔄 Serve daemon"
echo "──────────────────────────────────────────────"

if [[ "$OS" == "Darwin" ]]; then
    PLIST_SRC="$SCRIPT_DIR/com.claude.hookline-serve.plist"
    PLIST_DST="$HOME/Library/LaunchAgents/com.claude.hookline-serve.plist"

    mkdir -p "$HOME/Library/LaunchAgents"

    sed -e "s|__HOOKS_DIR__|$HOOKS_DIR|g" \
        -e "s|__BOT_TOKEN__|$TOKEN|g" \
        -e "s|__CHAT_ID__|$CHAT|g" \
        -e "s|__HOME__|$HOME|g" \
        "$PLIST_SRC" > "$PLIST_DST"

    launchctl unload "$PLIST_DST" 2>/dev/null || true
    if launchctl load "$PLIST_DST" 2>/dev/null; then
        echo "  ✅ launchd agent started (com.claude.hookline-serve)"
    else
        echo "  ⚠️  launchctl load failed"
        echo "     Start manually: launchctl load $PLIST_DST"
    fi
    echo "  📋 Logs: ~/.claude/hookline-state/serve.{stdout,stderr}.log"

elif [[ "$OS" == "Linux" ]]; then
    SYSTEMD_DIR="$HOME/.config/systemd/user"
    SERVICE_SRC="$SCRIPT_DIR/claude-hookline-serve.service"
    SERVICE_DST="$SYSTEMD_DIR/claude-hookline-serve.service"

    mkdir -p "$SYSTEMD_DIR"

    sed -e "s|__HOOKS_DIR__|$HOOKS_DIR|g" \
        -e "s|__BOT_TOKEN__|$TOKEN|g" \
        -e "s|__CHAT_ID__|$CHAT|g" \
        "$SERVICE_SRC" > "$SERVICE_DST"

    systemctl --user daemon-reload
    systemctl --user enable claude-hookline-serve.service
    systemctl --user restart claude-hookline-serve.service
    echo "  ✅ systemd service started (claude-hookline-serve)"
    echo "  📋 journalctl --user -u claude-hookline-serve -f"

else
    echo "  ⏭️  Skipped (unsupported OS: $OS)"
    echo "     Run manually: PYTHONPATH=~/.claude/hooks python3 -m hookline --serve"
fi

echo ""
echo "──────────────────────────────────────────────"
echo "🎣 Hookline ready!"
echo "──────────────────────────────────────────────"
echo ""
echo "  🔕 Notifications are OFF by default"
echo "     Toggle when starting long runs:"
echo ""
echo "  Claude Code (CLI / App / CoWork):"
echo "    /hookline on          Enable for current project"
echo "    /hookline on all      Enable for all projects"
echo "    /hookline off         Disable for current project"
echo "    /hookline off all     Disable all notifications"
echo "    /hookline status      Show what's enabled"
echo ""
echo "  Terminal (instant, no LLM turn):"
echo "    hookline-on           Enable for current dir"
echo "    hookline-off          Disable for current dir"
echo "    hookline-status       Show all active sentinels"
echo ""
echo "  ⚙️  Settings:  ~/.claude/hookline.json"
echo "  🎨 Emojis:    ~/.claude/hookline-projects.json"
echo ""
echo "  🤖 Serve daemon (auto-started):"
echo "     Handles mute, reply commands, tool approval"
echo "     Reply to notifications: log, full, errors, tools"
echo ""
echo "  ➜ source $PROFILE"
echo "──────────────────────────────────────────────"
