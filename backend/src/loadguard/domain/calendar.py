"""Business calendar: weekends, public holidays, half days and month-phase helpers.

Pure and immutable so it can be shared by live evaluation, replay and backtests.
"""

from __future__ import annotations

import calendar as _cal
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum


class MonthPhase(StrEnum):
    """Where a business day falls inside its month. Bill volumes are strongly month-phase dependent."""

    START = "START"  # first 3 business days
    MID = "MID"
    END = "END"  # last 3 business days


@dataclass(frozen=True)
class BusinessCalendar:
    code: str
    holidays: frozenset[date] = field(default_factory=frozenset)
    half_days: frozenset[date] = field(default_factory=frozenset)
    weekend: frozenset[int] = frozenset({6, 7})  # ISO weekday

    def is_business_day(self, d: date) -> bool:
        return d.isoweekday() not in self.weekend and d not in self.holidays

    def next_business_day(self, d: date, *, inclusive: bool = False) -> date:
        cur = d if inclusive else d + timedelta(days=1)
        while not self.is_business_day(cur):
            cur += timedelta(days=1)
        return cur

    def previous_business_day(self, d: date, *, inclusive: bool = False) -> date:
        cur = d if inclusive else d - timedelta(days=1)
        while not self.is_business_day(cur):
            cur -= timedelta(days=1)
        return cur

    def business_days_between(self, start: date, end: date) -> int:
        """Number of business days in (start, end]. Negative if end < start."""
        if end == start:
            return 0
        sign = 1 if end > start else -1
        lo, hi = (start, end) if sign == 1 else (end, start)
        n = 0
        cur = lo + timedelta(days=1)
        while cur <= hi:
            if self.is_business_day(cur):
                n += 1
            cur += timedelta(days=1)
        return n * sign

    def last_business_day_of_month(self, year: int, month: int) -> date:
        last = date(year, month, _cal.monthrange(year, month)[1])
        return self.previous_business_day(last, inclusive=True)

    def month_phase(self, d: date) -> MonthPhase:
        first = date(d.year, d.month, 1)
        last = date(d.year, d.month, _cal.monthrange(d.year, d.month)[1])
        # Count business days from the start/end of month up to d.
        from_start = sum(
            1 for i in range((d - first).days + 1) if self.is_business_day(first + timedelta(days=i))
        )
        from_end = sum(1 for i in range((last - d).days + 1) if self.is_business_day(d + timedelta(days=i)))
        if from_start <= 3:
            return MonthPhase.START
        if from_end <= 3:
            return MonthPhase.END
        return MonthPhase.MID
