"""Operational time helpers: one place that knows the operating timezone."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from loadguard.core import clock
from loadguard.core.config import get_settings


def ops_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().operating_timezone)


def ops_date(ts: datetime) -> date:
    return ts.astimezone(ops_tz()).date()


def ops_today() -> date:
    return ops_date(clock.now())
