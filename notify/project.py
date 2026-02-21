"""Project emoji configuration and labels."""
from __future__ import annotations

import json
from pathlib import Path

from notify.config import PROJECT_CONFIG_PATH

_project_config: dict | None = None


def _get_project_config() -> dict:
    """Load project config: {"attest": "...", "cairn": "...", ...}"""
    global _project_config
    if _project_config is None:
        try:
            _project_config = json.loads(PROJECT_CONFIG_PATH.read_text())
        except (OSError, json.JSONDecodeError):
            _project_config = {}
    return _project_config  # type: ignore[return-value]


def _project_emoji(project: str) -> str:
    """Get the emoji for a project, or empty string."""
    return _get_project_config().get(project, "")


def _project_label(project: str) -> str:
    """Format project name with optional emoji."""
    emoji = _project_emoji(project)
    if emoji:
        return f"{emoji} {project}"
    return project
