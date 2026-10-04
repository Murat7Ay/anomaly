"""Single source of 'now' so tests, replays and demos can control time."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

_now: Callable[[], datetime] = lambda: datetime.now(UTC)  # noqa: E731


def now() -> datetime:
    return _now()


def set_clock(fn: Callable[[], datetime]) -> None:
    global _now
    _now = fn


def reset_clock() -> None:
    set_clock(lambda: datetime.now(UTC))
