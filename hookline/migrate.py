"""Migration from old 'notify' naming to 'hookline'."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


CLAUDE_DIR = Path.home() / ".claude"

_OLD_STATE_DIR = CLAUDE_DIR / "notify-state"
_NEW_STATE_DIR = CLAUDE_DIR / "hookline-state"

_OLD_CONFIG = CLAUDE_DIR / "notify-config.json"
_NEW_CONFIG = CLAUDE_DIR / "hookline.json"

_OLD_PROJECTS = CLAUDE_DIR / "notify-projects.json"
_NEW_PROJECTS = CLAUDE_DIR / "hookline-projects.json"

_SETTINGS = CLAUDE_DIR / "settings.json"

_OLD_SENTINEL_PREFIX = "notify-enabled"
_NEW_SENTINEL_PREFIX = "hookline-enabled"


def _migrate_dir(old: Path, new: Path) -> bool:
    """Copy directory tree from old to new. Returns True if action was taken."""
    if not old.exists():
        return False
    if new.exists():
        print(f"  skip  {new.name}  (already exists)")
        return False
    shutil.copytree(old, new)
    print(f"  copy  {old.name} -> {new.name}")
    return True


def _migrate_file(old: Path, new: Path) -> bool:
    """Copy file from old to new. Returns True if action was taken."""
    if not old.exists():
        return False
    if new.exists():
        print(f"  skip  {new.name}  (already exists)")
        return False
    shutil.copy2(old, new)
    print(f"  copy  {old.name} -> {new.name}")
    return True


def _migrate_sentinels() -> int:
    """Rename notify-enabled* sentinel files to hookline-enabled*. Returns count renamed."""
    renamed = 0
    for sentinel in CLAUDE_DIR.glob(f"{_OLD_SENTINEL_PREFIX}*"):
        suffix = sentinel.name[len(_OLD_SENTINEL_PREFIX):]
        new_sentinel = CLAUDE_DIR / f"{_NEW_SENTINEL_PREFIX}{suffix}"
        if new_sentinel.exists():
            print(f"  skip  {sentinel.name}  (target already exists)")
            continue
        sentinel.rename(new_sentinel)
        print(f"  rename  {sentinel.name} -> {new_sentinel.name}")
        renamed += 1
    return renamed


def _migrate_settings() -> bool:
    """Replace 'python3 -m notify' with 'python3 -m hookline' in settings.json hooks."""
    if not _SETTINGS.exists():
        return False

    raw = _SETTINGS.read_text(encoding="utf-8")
    old_cmd = "python3 -m notify"
    new_cmd = "python3 -m hookline"

    if old_cmd not in raw:
        return False

    updated = raw.replace(old_cmd, new_cmd)

    # Validate JSON is still well-formed before writing
    try:
        json.loads(updated)
    except json.JSONDecodeError as exc:
        print(f"  error  settings.json would become invalid JSON after substitution: {exc}")
        return False

    _SETTINGS.write_text(updated, encoding="utf-8")
    count = raw.count(old_cmd)
    print(f"  update  settings.json  ({count} hook command{'s' if count != 1 else ''} updated)")
    return True


def migrate() -> None:
    """Run all migration steps idempotently."""
    print("hookline migration: notify -> hookline")
    print(f"  working in {CLAUDE_DIR}")
    print()

    actions: dict[str, bool | int] = {}

    print("1. state directory")
    actions["state_dir"] = _migrate_dir(_OLD_STATE_DIR, _NEW_STATE_DIR)

    print("2. config file")
    actions["config"] = _migrate_file(_OLD_CONFIG, _NEW_CONFIG)

    print("3. projects file")
    actions["projects"] = _migrate_file(_OLD_PROJECTS, _NEW_PROJECTS)

    print("4. sentinel files")
    actions["sentinels"] = _migrate_sentinels()

    print("5. settings.json hooks")
    actions["settings"] = _migrate_settings()

    print()
    _print_summary(actions)


def _print_summary(actions: dict[str, bool | int]) -> None:
    total_actions = sum(
        (v if isinstance(v, int) else int(bool(v))) for v in actions.values()
    )
    if total_actions == 0:
        print("migration complete: nothing to do (already migrated or no old files found)")
    else:
        print(f"migration complete: {total_actions} action(s) performed")
        if actions["state_dir"]:
            print(f"  - copied notify-state/ -> hookline-state/")
        if actions["config"]:
            print(f"  - copied notify-config.json -> hookline.json")
        if actions["projects"]:
            print(f"  - copied notify-projects.json -> hookline-projects.json")
        sentinel_count = actions["sentinels"]
        if sentinel_count:
            print(f"  - renamed {sentinel_count} sentinel file(s)")
        if actions["settings"]:
            print(f"  - updated settings.json hook commands")


if __name__ == "__main__":
    migrate()
