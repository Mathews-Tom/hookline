#!/usr/bin/env bash
# toggle.sh — Enable/disable/reset Telegram notifications, scoped by project.
#
# Usage:
#   toggle.sh on    [project|all]    Enable notifications
#   toggle.sh off   [project|all]    Disable notifications
#   toggle.sh reset [project|all]    Start a new thread (between task runs)
#   toggle.sh status                 Show what's enabled
#   toggle.sh                        Toggle current project
#
# Scoping:
#   /notify on            → enables for current directory's project name
#   /notify on all        → enables globally (all projects)
#   /notify on attest     → enables for "attest" specifically
#   /notify off           → disables current project
#   /notify off all       → disables global + all project sentinels
#
# Sentinel files:
#   ~/.claude/notify-enabled.{project}   project-scoped
#   ~/.claude/notify-enabled             global (all projects)
#
# notify package checks: project sentinel OR global sentinel -> send.

set -euo pipefail

SENTINEL_DIR="$HOME/.claude"

# Resolve project name: explicit arg > basename of cwd
_resolve_project() {
    local arg="${1:-}"
    if [[ -n "$arg" && "$arg" != "all" ]]; then
        echo "$arg"
    elif [[ "$arg" == "all" ]]; then
        echo "all"
    else
        basename "$(pwd)"
    fi
}

_sentinel_path() {
    local project="$1"
    if [[ "$project" == "all" ]]; then
        echo "$SENTINEL_DIR/notify-enabled"
    else
        echo "$SENTINEL_DIR/notify-enabled.$project"
    fi
}

_on() {
    local project="$1"
    local sentinel
    sentinel=$(_sentinel_path "$project")
    mkdir -p "$SENTINEL_DIR"
    date -u '+%Y-%m-%dT%H:%M:%SZ' > "$sentinel"
    # Clear stale session state
    if [[ "$project" == "all" ]]; then
        rm -rf "$HOME/.claude/notify-state/"*
    else
        rm -rf "$HOME/.claude/notify-state/${project}"
    fi
    if [[ "$project" == "all" ]]; then
        echo "🔔 Notifications ON (all projects)"
    else
        echo "🔔 Notifications ON for $project"
    fi
}

_off() {
    local project="$1"
    if [[ "$project" == "all" ]]; then
        # Remove global + all project sentinels
        rm -f "$SENTINEL_DIR"/notify-enabled
        rm -f "$SENTINEL_DIR"/notify-enabled.*
        echo "🔕 Notifications OFF (all cleared)"
    else
        local sentinel
        sentinel=$(_sentinel_path "$project")
        rm -f "$sentinel"
        echo "🔕 Notifications OFF for $project"
    fi
}

_reset() {
    local project="$1"
    local state_dir="$HOME/.claude/notify-state"
    if [[ "$project" == "all" ]]; then
        # Reset all project state directories
        for d in "$state_dir"/*/; do
            [[ -d "$d" ]] || continue
            rm -f "$d/thread.json" "$d/tasks.json" "$d/debounce.json"
        done
        echo "📌 Thread reset (all projects) — next notification starts a new thread"
    else
        local pdir="$state_dir/$project"
        if [[ -d "$pdir" ]]; then
            rm -f "$pdir/thread.json" "$pdir/tasks.json" "$pdir/debounce.json"
        fi
        echo "📌 Thread reset for $project — next notification starts a new thread"
    fi
}

_status() {
    local found=false
    # Check global
    if [[ -f "$SENTINEL_DIR/notify-enabled" ]]; then
        local since
        since=$(cat "$SENTINEL_DIR/notify-enabled" 2>/dev/null || echo "unknown")
        echo "🔔 Global: ON (since $since)"
        found=true
    fi
    # Check project-scoped
    for f in "$SENTINEL_DIR"/notify-enabled.*; do
        [[ -f "$f" ]] || continue
        local proj="${f##*.notify-enabled.}"
        proj="${f#$SENTINEL_DIR/notify-enabled.}"
        local since
        since=$(cat "$f" 2>/dev/null || echo "unknown")
        echo "🔔 $proj: ON (since $since)"
        found=true
    done
    if [[ "$found" == "false" ]]; then
        echo "🔕 Notifications are OFF"
    fi

    # Check serve daemon (PID file, then OS-specific service manager)
    local pid_file="$HOME/.claude/notify-state/serve.pid"
    local daemon_found=false
    if [[ -f "$pid_file" ]]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null)
        if kill -0 "$pid" 2>/dev/null; then
            echo "🟢 Serve daemon: running (PID $pid)"
            daemon_found=true
        else
            echo "🔴 Serve daemon: stale PID file (not running)"
        fi
    fi
    if [[ "$daemon_found" == "false" ]]; then
        if [[ "$(uname -s)" == "Linux" ]] && command -v systemctl &>/dev/null; then
            if systemctl --user is-active claude-notify-serve.service &>/dev/null; then
                echo "🟢 Serve daemon: running (systemd)"
            else
                echo "⚪ Serve daemon: not running"
            fi
        elif [[ "$(uname -s)" == "Darwin" ]]; then
            if launchctl list com.claude.notify-serve &>/dev/null 2>&1; then
                echo "🟢 Serve daemon: running (launchd)"
            else
                echo "⚪ Serve daemon: not running"
            fi
        else
            echo "⚪ Serve daemon: not running"
        fi
    fi
}

ACTION="${1:-toggle}"
SCOPE="${2:-}"

case "$ACTION" in
    on)
        PROJECT=$(_resolve_project "$SCOPE")
        _on "$PROJECT"
        ;;
    off)
        PROJECT=$(_resolve_project "$SCOPE")
        _off "$PROJECT"
        ;;
    reset)
        PROJECT=$(_resolve_project "$SCOPE")
        _reset "$PROJECT"
        ;;
    status)
        _status
        ;;
    toggle)
        PROJECT=$(_resolve_project "$SCOPE")
        SENTINEL=$(_sentinel_path "$PROJECT")
        if [[ -f "$SENTINEL" ]]; then
            _off "$PROJECT"
        else
            _on "$PROJECT"
        fi
        ;;
    doctor|health)
        HOOKS_DIR="$HOME/.claude/hooks"
        python3 "$HOOKS_DIR/notify" --health
        ;;
    *)
        echo "Usage: toggle.sh [on|off|reset|status|doctor|toggle] [project|all]"
        exit 1
        ;;
esac
