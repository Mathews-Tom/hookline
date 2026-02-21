"""Logging utility for claude-notify."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

_serve_logger: logging.Logger | None = None


def setup_serve_logging(state_dir: Path) -> None:
    """Configure rotating file handler for serve daemon."""
    global _serve_logger
    log_path = state_dir / "serve.log"
    state_dir.mkdir(parents=True, exist_ok=True)
    _serve_logger = logging.getLogger("claude-notify-serve")
    _serve_logger.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=3,
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _serve_logger.addHandler(handler)


def log(msg: str) -> None:
    """Log to stderr (hook mode) or rotating file (serve mode)."""
    if _serve_logger:
        _serve_logger.info(msg)
    print(f"[claude-notify] {msg}", file=sys.stderr)
