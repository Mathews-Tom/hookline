"""Cron-like task scheduler for proactive features."""
from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime, timezone

from hookline._log import log
from hookline.config import STATE_DIR

_SCHEDULE_STATE_FILE = STATE_DIR / "scheduler.json"

# Registry of scheduled tasks
_tasks: dict[str, ScheduledTask] = {}


class CronExpr:
    """Simple 5-field cron expression parser.

    Fields: minute hour day-of-month month day-of-week
    Supports: * (any), N (exact), N-M (range), */N (step), N,M (list)
    Day-of-week: 0=Monday .. 6=Sunday (Python weekday convention).
    """

    def __init__(self, expr: str) -> None:
        parts = expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"Cron expression requires 5 fields, got {len(parts)}: {expr!r}")
        self.minute = self._parse_field(parts[0], 0, 59)
        self.hour = self._parse_field(parts[1], 0, 23)
        self.dom = self._parse_field(parts[2], 1, 31)
        self.month = self._parse_field(parts[3], 1, 12)
        self.dow = self._parse_field(parts[4], 0, 6)

    @staticmethod
    def _parse_field(field: str, min_val: int, max_val: int) -> set[int] | None:
        """Parse a single cron field. Returns None for '*' (match any)."""
        if field == "*":
            return None
        values: set[int] = set()
        for part in field.split(","):
            if "/" in part:
                base, step_str = part.split("/", 1)
                start = min_val if base == "*" else int(base)
                step = int(step_str)
                if step <= 0:
                    raise ValueError(f"Step must be positive: {field!r}")
                for v in range(start, max_val + 1, step):
                    values.add(v)
            elif "-" in part:
                lo, hi = part.split("-", 1)
                lo_int, hi_int = int(lo), int(hi)
                if lo_int > hi_int:
                    raise ValueError(f"Invalid range: {field!r}")
                for v in range(lo_int, hi_int + 1):
                    values.add(v)
            else:
                val = int(part)
                if val < min_val or val > max_val:
                    raise ValueError(f"Value {val} out of range [{min_val}, {max_val}]")
                values.add(val)
        return values

    def matches(self, dt: datetime) -> bool:
        """Check if a datetime matches this cron expression."""
        if self.minute is not None and dt.minute not in self.minute:
            return False
        if self.hour is not None and dt.hour not in self.hour:
            return False
        if self.dom is not None and dt.day not in self.dom:
            return False
        if self.month is not None and dt.month not in self.month:
            return False
        if self.dow is not None and dt.weekday() not in self.dow:
            return False
        return True


class ScheduledTask:
    """A task triggered by cron expression or fixed interval."""

    def __init__(
        self,
        name: str,
        handler: Callable[[], None],
        *,
        cron: str | None = None,
        interval_minutes: int | None = None,
    ) -> None:
        self.name = name
        self.handler = handler
        self.cron_expr = CronExpr(cron) if cron else None
        self.interval_seconds = interval_minutes * 60 if interval_minutes else None
        self.last_run: float = 0.0

        if not self.cron_expr and not self.interval_seconds:
            raise ValueError(f"Task {name!r} requires either cron or interval_minutes")

    def should_run(self, now: datetime, now_ts: float) -> bool:
        """Determine if this task should fire now."""
        if self.cron_expr:
            if not self.cron_expr.matches(now):
                return False
            # Prevent re-running within the same minute
            if self.last_run > 0:
                last_dt = datetime.fromtimestamp(self.last_run, tz=timezone.utc)
                if (
                    last_dt.year == now.year
                    and last_dt.month == now.month
                    and last_dt.day == now.day
                    and last_dt.hour == now.hour
                    and last_dt.minute == now.minute
                ):
                    return False
            return True

        if self.interval_seconds:
            return (now_ts - self.last_run) >= self.interval_seconds

        return False


def register_task(
    name: str,
    handler: Callable[[], None],
    *,
    cron: str | None = None,
    interval_minutes: int | None = None,
) -> None:
    """Register a scheduled task."""
    _tasks[name] = ScheduledTask(name, handler, cron=cron, interval_minutes=interval_minutes)


def unregister_all() -> None:
    """Remove all registered tasks. Used in testing."""
    _tasks.clear()


def _load_state() -> dict[str, float]:
    """Load last-run timestamps from persistent state."""
    try:
        return json.loads(_SCHEDULE_STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: dict[str, float]) -> None:
    """Save last-run timestamps to persistent state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _SCHEDULE_STATE_FILE.write_text(json.dumps(state))


def tick() -> None:
    """Check all registered tasks and run those that are due.

    Called from the serve daemon polling loop on each iteration.
    """
    if not _tasks:
        return

    now = datetime.now(timezone.utc)
    now_ts = time.time()

    state = _load_state()
    for name, task in _tasks.items():
        if name in state:
            task.last_run = state[name]

    ran_any = False
    for name, task in _tasks.items():
        if task.should_run(now, now_ts):
            try:
                task.handler()
                task.last_run = now_ts
                state[name] = now_ts
                ran_any = True
                log(f"Scheduler: ran {name}")
            except Exception as e:
                log(f"Scheduler error ({name}): {e}")

    if ran_any:
        _save_state(state)


def get_status() -> list[dict[str, str | float | bool | None]]:
    """Return status of all registered tasks for display."""
    state = _load_state()
    result: list[dict[str, str | float | bool | None]] = []
    for name, task in _tasks.items():
        last = state.get(name, 0.0)
        result.append({
            "name": name,
            "type": "cron" if task.cron_expr else "interval",
            "last_run": last if last > 0 else None,
        })
    return result
