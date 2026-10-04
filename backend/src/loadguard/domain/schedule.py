"""Expand a contract into concrete expected deliveries ("occurrences") on the business calendar."""

from __future__ import annotations

import calendar as _cal
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from loadguard.domain.calendar import BusinessCalendar
from loadguard.domain.contract import Cadence, ContractSpec, DeliverySlot, HolidayShift


@dataclass(frozen=True)
class ExpectedOccurrence:
    slot_key: str
    business_date: date
    nominal_date: date
    window_start_utc: datetime
    deadline_utc: datetime  # includes grace

    @property
    def shifted(self) -> bool:
        return self.business_date != self.nominal_date


def local_to_utc(d: date, t: time, tz: str) -> datetime:
    return datetime.combine(d, t, tzinfo=ZoneInfo(tz)).astimezone(UTC)


def local_date(ts: datetime, tz: str) -> date:
    return ts.astimezone(ZoneInfo(tz)).date()


def local_minutes(ts: datetime, tz: str) -> int:
    lt = ts.astimezone(ZoneInfo(tz))
    return lt.hour * 60 + lt.minute


def _nominal_dates(slot: DeliverySlot, cal: BusinessCalendar, start: date, end: date) -> Iterator[date]:
    if slot.cadence in (Cadence.BUSINESS_DAYS, Cadence.EVERY_DAY):
        cur = start
        while cur <= end:
            if slot.cadence == Cadence.EVERY_DAY or cal.is_business_day(cur):
                yield cur
            cur += timedelta(days=1)
        return
    if slot.cadence == Cadence.WEEKLY:
        days = set(slot.weekdays or [])
        cur = start
        while cur <= end:
            if cur.isoweekday() in days:
                yield cur
            cur += timedelta(days=1)
        return
    # MONTHLY
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        last = _cal.monthrange(y, m)[1]
        for d in slot.month_days or []:
            yield date(y, m, min(d, last))
        if slot.last_business_day:
            yield cal.last_business_day_of_month(y, m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _shift(slot: DeliverySlot, cal: BusinessCalendar, d: date) -> date | None:
    if slot.cadence in (Cadence.BUSINESS_DAYS, Cadence.EVERY_DAY) or cal.is_business_day(d):
        return d
    match slot.holiday_shift:
        case HolidayShift.NEXT_BUSINESS_DAY:
            return cal.next_business_day(d)
        case HolidayShift.PREVIOUS_BUSINESS_DAY:
            return cal.previous_business_day(d)
        case HolidayShift.SKIP:
            return None
        case HolidayShift.NONE:
            return d


def expected_occurrences(
    spec: ContractSpec, cal: BusinessCalendar, start: date, end: date
) -> list[ExpectedOccurrence]:
    """All expected occurrences whose business date falls in [start, end], sorted by deadline."""
    out: dict[tuple[str, date], ExpectedOccurrence] = {}
    pad = timedelta(days=10)  # shifted dates may come from just outside the range
    for slot in spec.slots:
        for nominal in _nominal_dates(slot, cal, start - pad, end + pad):
            bd = _shift(slot, cal, nominal)
            if bd is None or not (start <= bd <= end):
                continue
            key = (slot.key, bd)
            if key in out:  # two nominal dates collapsed onto one business day: one delivery expected
                continue
            out[key] = ExpectedOccurrence(
                slot_key=slot.key,
                business_date=bd,
                nominal_date=nominal,
                window_start_utc=local_to_utc(bd, slot.window_start, spec.timezone),
                deadline_utc=local_to_utc(bd, slot.deadline, spec.timezone)
                + timedelta(minutes=slot.grace_minutes),
            )
    return sorted(out.values(), key=lambda o: (o.deadline_utc, o.slot_key))
