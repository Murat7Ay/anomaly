"""Assign an arriving file to the occurrence it most plausibly fulfils.

Integrations should pass a slot hint (e.g. from the file-name pattern) whenever possible; the
heuristic below is the deterministic fallback and is documented in docs/DOMAIN.md.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from loadguard.domain.calendar import BusinessCalendar
from loadguard.domain.contract import UNSCHEDULED_SLOT, Cadence, ContractSpec
from loadguard.domain.schedule import ExpectedOccurrence, expected_occurrences, local_date

LATE_LOOKBACK_DAYS = 4


@dataclass(frozen=True)
class Assignment:
    slot_key: str
    business_date: date
    expected: ExpectedOccurrence | None
    reason: str  # ON_TIME | LATE | EARLY | ADDITIONAL | HINT | UNSCHEDULED


def assign_load(
    received_at: datetime,
    spec: ContractSpec,
    cal: BusinessCalendar,
    is_filled: Callable[[str, date], bool],
    slot_hint: str | None = None,
) -> Assignment:
    d = local_date(received_at, spec.timezone)
    window = expected_occurrences(spec, cal, d - timedelta(days=LATE_LOOKBACK_DAYS), d + timedelta(days=1))
    today = [o for o in window if o.business_date == d]
    unfilled_today = [o for o in today if not is_filled(o.slot_key, d)]

    def pick(o: ExpectedOccurrence, reason: str) -> Assignment:
        return Assignment(o.slot_key, o.business_date, o, reason)

    if slot_hint and spec.slot(slot_hint):
        cands = [o for o in window if o.slot_key == slot_hint and o.business_date <= d]
        open_ = [o for o in cands if not is_filled(o.slot_key, o.business_date)]
        if open_:
            o = max(open_, key=lambda x: x.business_date)
            return pick(o, "HINT")
        if cands:
            return pick(max(cands, key=lambda x: x.business_date), "ADDITIONAL")

    in_window = [o for o in unfilled_today if o.window_start_utc <= received_at <= o.deadline_utc]
    if in_window:
        return pick(min(in_window, key=lambda o: o.deadline_utc), "ON_TIME")

    overdue = [o for o in unfilled_today if o.deadline_utc < received_at]
    if overdue:
        return pick(min(overdue, key=lambda o: o.deadline_utc), "LATE")

    filled_today = [o for o in today if is_filled(o.slot_key, d)]
    if filled_today:
        after = [o for o in filled_today if o.deadline_utc >= received_at]
        target = (
            min(after, key=lambda o: o.deadline_utc)
            if after
            else max(filled_today, key=lambda o: o.deadline_utc)
        )
        return pick(target, "ADDITIONAL")

    if unfilled_today:  # arrived before the window opened
        return pick(min(unfilled_today, key=lambda o: o.deadline_utc), "EARLY")

    past_open = [o for o in window if o.business_date < d and not is_filled(o.slot_key, o.business_date)]
    if past_open:
        return pick(max(past_open, key=lambda o: o.deadline_utc), "LATE")

    tomorrow = [
        o
        for o in window
        if o.business_date == d + timedelta(days=1)
        and not is_filled(o.slot_key, o.business_date)
        and spec.slot(o.slot_key) is not None
        and spec.slot(o.slot_key).cadence in (Cadence.WEEKLY, Cadence.MONTHLY)  # type: ignore[union-attr]
    ]
    if tomorrow:
        return pick(min(tomorrow, key=lambda o: o.deadline_utc), "EARLY")

    return Assignment(UNSCHEDULED_SLOT, d, None, "UNSCHEDULED")
