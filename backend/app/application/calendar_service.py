from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta

from app.domain.enums import ShiftRule
from app.infra.repositories.calendar_repo import CalendarRepository


def is_weekend(d: date) -> bool:
    # Python: Monday=0 ... Sunday=6
    return d.weekday() >= 5


@dataclass(frozen=True)
class CalendarWindow:
    calendar_id: uuid.UUID
    start_date: date
    end_date: date
    holiday_dates: frozenset[date]

    def is_holiday(self, d: date) -> bool:
        return d in self.holiday_dates

    def is_business_day(self, d: date) -> bool:
        return (not is_weekend(d)) and (d not in self.holiday_dates)


class CalendarService:
    """
    Business-day and holiday utilities.

    For deterministic evaluation, callers should obtain a CalendarWindow once per evaluation and
    reuse it so a single consistent holiday set is used throughout the decision run.
    """

    def __init__(self, repo: CalendarRepository) -> None:
        self._repo = repo

    def build_window(
        self,
        *,
        calendar_id: uuid.UUID,
        center: date,
        days_before: int = 500,
        days_after: int = 200,
    ) -> CalendarWindow:
        start = center - timedelta(days=days_before)
        end = center + timedelta(days=days_after)
        holidays = self._repo.holiday_dates_in_range(calendar_id=calendar_id, start_date=start, end_date=end)
        return CalendarWindow(
            calendar_id=calendar_id,
            start_date=start,
            end_date=end,
            holiday_dates=frozenset(holidays),
        )

    def build_window_for_range(
        self, *, calendar_id: uuid.UUID, start_date: date, end_date: date
    ) -> CalendarWindow:
        if end_date < start_date:
            raise ValueError("invalid_date_range")
        holidays = self._repo.holiday_dates_in_range(
            calendar_id=calendar_id, start_date=start_date, end_date=end_date
        )
        return CalendarWindow(
            calendar_id=calendar_id,
            start_date=start_date,
            end_date=end_date,
            holiday_dates=frozenset(holidays),
        )

    def next_business_day(self, window: CalendarWindow, d: date) -> date:
        cur = d + timedelta(days=1)
        for _ in range(366):
            if window.is_business_day(cur):
                return cur
            cur += timedelta(days=1)
        raise ValueError("next_business_day_search_exceeded")

    def prev_business_day(self, window: CalendarWindow, d: date) -> date:
        cur = d - timedelta(days=1)
        for _ in range(366):
            if window.is_business_day(cur):
                return cur
            cur -= timedelta(days=1)
        raise ValueError("prev_business_day_search_exceeded")

    def shift(self, *, window: CalendarWindow, anchor: date, rule: ShiftRule) -> date:
        if rule == ShiftRule.NONE:
            return anchor
        if window.is_business_day(anchor):
            return anchor

        if rule == ShiftRule.NEXT_BUSINESS_DAY:
            return self.next_business_day(window, anchor)
        if rule == ShiftRule.PREV_BUSINESS_DAY:
            return self.prev_business_day(window, anchor)
        if rule == ShiftRule.NEAREST_BUSINESS_DAY:
            prev_bd = self.prev_business_day(window, anchor)
            next_bd = self.next_business_day(window, anchor)
            # Deterministic tie-break: prefer next business day
            prev_dist = (anchor - prev_bd).days
            next_dist = (next_bd - anchor).days
            return next_bd if next_dist <= prev_dist else prev_bd

        raise ValueError(f"unsupported_shift_rule:{rule}")


