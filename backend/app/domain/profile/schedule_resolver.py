from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from dateutil.relativedelta import relativedelta

from app.application.calendar_service import CalendarService, CalendarWindow
from app.domain.profile.config import Cadence, DailyKind, OccurrenceSpec, ScheduleSpec


@dataclass(frozen=True)
class ExpectedOccurrenceDate:
    """
    A single expected load occurrence after applying business-day/holiday shifting.

    - `anchor_date`: the nominal calendar anchor (e.g., 15th of the month)
    - `expected_date`: the date the load is expected to arrive after shift rules
    """

    occurrence_id: str
    anchor_date: date
    expected_date: date
    shifted: bool

    expected_by_run: str
    grace_minutes: int
    max_late_business_days: int

    shift_rule: str
    cadence: str


class ScheduleResolver:
    """
    Resolves expected dates from a profile schedule spec against a business calendar.

    Determinism rule: if multiple occurrences resolve to the same expected_date, the resolver
    returns them all; downstream layers must handle collisions explicitly (no implicit merging).
    """

    def __init__(self, calendar_service: CalendarService) -> None:
        self._cal = calendar_service

    def expected_occurrences_for_range(
        self,
        *,
        schedule: ScheduleSpec,
        window: CalendarWindow,
        start_date: date,
        end_date: date,
        pad_days: int = 40,
    ) -> list[ExpectedOccurrenceDate]:
        if end_date < start_date:
            raise ValueError("invalid_date_range")

        # Pad anchor generation to allow shift rules to land inside [start_date, end_date].
        anchor_start = start_date - timedelta(days=pad_days)
        anchor_end = end_date + timedelta(days=pad_days)

        out: list[ExpectedOccurrenceDate] = []
        for occ in schedule.occurrences:
            for anchor in self._anchors_for_occurrence(occ=occ, window=window, start=anchor_start, end=anchor_end):
                expected = self._resolve_expected_date(occ=occ, window=window, anchor=anchor)
                if start_date <= expected <= end_date:
                    out.append(
                        ExpectedOccurrenceDate(
                            occurrence_id=occ.occurrence_id,
                            anchor_date=anchor,
                            expected_date=expected,
                            shifted=(expected != anchor),
                            expected_by_run=occ.expected_by_run,
                            grace_minutes=occ.grace_minutes,
                            max_late_business_days=occ.max_late_business_days,
                            shift_rule=occ.shift_rule.value,
                            cadence=occ.cadence.value,
                        )
                    )
        out.sort(key=lambda x: (x.expected_date, x.occurrence_id))
        return out

    def expected_by_date(
        self,
        *,
        schedule: ScheduleSpec,
        window: CalendarWindow,
        start_date: date,
        end_date: date,
    ) -> dict[date, list[ExpectedOccurrenceDate]]:
        occs = self.expected_occurrences_for_range(
            schedule=schedule, window=window, start_date=start_date, end_date=end_date
        )
        by_date: dict[date, list[ExpectedOccurrenceDate]] = {}
        for o in occs:
            by_date.setdefault(o.expected_date, []).append(o)
        return by_date

    def _resolve_expected_date(self, *, occ: OccurrenceSpec, window: CalendarWindow, anchor: date) -> date:
        # Special case: schedule explicitly says "last_business_day". That is already a business day.
        if occ.cadence == Cadence.MONTHLY and bool(occ.last_business_day):
            return anchor
        return self._cal.shift(window=window, anchor=anchor, rule=occ.shift_rule)

    def _anchors_for_occurrence(
        self, *, occ: OccurrenceSpec, window: CalendarWindow, start: date, end: date
    ) -> list[date]:
        if occ.cadence == Cadence.DAILY:
            return self._anchors_daily(occ=occ, window=window, start=start, end=end)
        if occ.cadence == Cadence.WEEKLY:
            return self._anchors_weekly(occ=occ, start=start, end=end)
        if occ.cadence == Cadence.BIWEEKLY:
            return self._anchors_biweekly(occ=occ, start=start, end=end)
        if occ.cadence == Cadence.MONTHLY:
            return self._anchors_monthly(occ=occ, window=window, start=start, end=end)
        if occ.cadence == Cadence.SPECIFIC_DATES:
            return self._anchors_specific_dates(occ=occ, start=start, end=end)
        raise ValueError(f"unsupported_cadence:{occ.cadence}")

    def _anchors_daily(self, *, occ: OccurrenceSpec, window: CalendarWindow, start: date, end: date) -> list[date]:
        if occ.daily_kind is None:
            raise ValueError("daily_kind_required")

        cur = start
        out: list[date] = []
        while cur <= end:
            if occ.daily_kind == DailyKind.ALL_DAYS:
                out.append(cur)
            elif occ.daily_kind == DailyKind.BUSINESS_DAYS:
                if window.is_business_day(cur):
                    out.append(cur)
            else:
                raise ValueError("unsupported_daily_kind")
            cur += timedelta(days=1)
        return out

    def _anchors_weekly(self, *, occ: OccurrenceSpec, start: date, end: date) -> list[date]:
        if not occ.days_of_week_iso:
            raise ValueError("days_of_week_iso_required")

        wanted = set(occ.days_of_week_iso)
        cur = start
        out: list[date] = []
        while cur <= end:
            if cur.isoweekday() in wanted:
                out.append(cur)
            cur += timedelta(days=1)
        return out

    def _anchors_biweekly(self, *, occ: OccurrenceSpec, start: date, end: date) -> list[date]:
        if occ.biweekly_anchor_date is None or occ.biweekly_weekday_iso is None:
            raise ValueError("biweekly_anchor_date_and_weekday_required")

        anchor = occ.biweekly_anchor_date
        # Align to the first occurrence >= start
        if anchor < start:
            delta_days = (start - anchor).days
            k = (delta_days + 13) // 14  # ceil
            anchor = anchor + timedelta(days=14 * k)

        out: list[date] = []
        cur = anchor
        while cur <= end:
            out.append(cur)
            cur += timedelta(days=14)
        return out

    def _anchors_monthly(
        self, *, occ: OccurrenceSpec, window: CalendarWindow, start: date, end: date
    ) -> list[date]:
        out: list[date] = []

        month_cursor = date(start.year, start.month, 1)
        month_end = date(end.year, end.month, 1)

        while month_cursor <= month_end:
            y = month_cursor.year
            m = month_cursor.month
            last_day = (month_cursor + relativedelta(months=1) - timedelta(days=1)).day

            if occ.days_of_month:
                for d in occ.days_of_month:
                    out.append(date(y, m, min(d, last_day)))

            if bool(occ.last_business_day):
                last = date(y, m, last_day)
                cur = last
                # Scan backwards within a safe bound
                for _ in range(40):
                    if window.is_business_day(cur):
                        out.append(cur)
                        break
                    cur -= timedelta(days=1)
                else:
                    raise ValueError("last_business_day_search_exceeded")

            month_cursor = month_cursor + relativedelta(months=1)

        return out

    def _anchors_specific_dates(self, *, occ: OccurrenceSpec, start: date, end: date) -> list[date]:
        if not occ.month_day_patterns:
            raise ValueError("month_day_patterns_required")
        out: list[date] = []
        for year in range(start.year, end.year + 1):
            for md in occ.month_day_patterns:
                mm_s, dd_s = md.split("-")
                mm = int(mm_s)
                dd = int(dd_s)
                try:
                    d = date(year, mm, dd)
                except ValueError:
                    # e.g. 02-29 in non-leap years: no anchor that year
                    continue
                if start <= d <= end:
                    out.append(d)
        return out


