"""Deterministic replay of the whole pipeline (assignment -> evaluation) over a period, fully in memory.

Used for: contract backtests before approval, detector regression tests on labelled simulations,
and bulk backfills. Live processing uses the same building blocks, so results are comparable.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from loadguard.domain.calendar import BusinessCalendar
from loadguard.domain.contract import UNSCHEDULED_SLOT, ContractSpec
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.engine import EvalResult, evaluate
from loadguard.domain.matching import assign_load
from loadguard.domain.model import HistoryPoint, LoadFacts
from loadguard.domain.schedule import ExpectedOccurrence, expected_occurrences

# Findings whose occurrence metrics are, by construction, not representative of the biller's normal.
HISTORY_DAYS = 400  # > 1 year so annual seasonality can be learned

NON_REPRESENTATIVE_CODES = frozenset({"DUPLICATE_FILE", "UNIT_SCALE_SUSPECT", "STALE_DATA"})


class Label:
    EXCLUDE = "EXCLUDE"  # confirmed anomaly or one-off event: do not learn from it
    REGIME = "REGIME"  # confirmed permanent new normal starting here


@dataclass
class ReplayOccurrence:
    slot_key: str
    business_date: date
    expected: ExpectedOccurrence | None
    loads: list[LoadFacts] = field(default_factory=list)
    result: EvalResult | None = None


def history_point(occ: ReplayOccurrence, cal: BusinessCalendar, label: str | None) -> HistoryPoint | None:
    if occ.result is None or not occ.result.metrics or occ.expected is None:
        return None
    codes = {f.code for f in occ.result.findings}
    return HistoryPoint(
        business_date=occ.business_date,
        weekday=occ.business_date.isoweekday(),
        month_phase=cal.month_phase(occ.business_date),
        metrics=occ.result.metrics,
        first_arrival_minutes=occ.result.first_arrival_minutes,
        excluded=label == Label.EXCLUDE or bool(codes & NON_REPRESENTATIVE_CODES),
        regime_break=label == Label.REGIME,
    )


def replay(
    *,
    spec_for: Callable[[date], ContractSpec],
    calendar: BusinessCalendar,
    loads: list[LoadFacts],
    start: date,
    end: date,
    now: datetime,
    labels: dict[tuple[str, date], str] | None = None,
    slot_hints: dict[str, str] | None = None,
    engine: Callable[[EvalContext], EvalResult] = evaluate,
) -> list[ReplayOccurrence]:
    """Replay [start, end]. Loads before `start` are used to warm up history but are not reported."""
    labels = labels or {}
    slot_hints = slot_hints or {}
    loads = sorted(loads, key=lambda lf: lf.received_at)
    first_day = min([start] + [lf.received_at.date() for lf in loads[:1]]) - timedelta(days=1)

    occs: dict[tuple[str, date], ReplayOccurrence] = {}
    d = first_day
    while d <= end:
        spec = spec_for(d)
        for e in expected_occurrences(spec, calendar, d, d):
            occs[(e.slot_key, d)] = ReplayOccurrence(e.slot_key, d, e)
        d += timedelta(days=1)

    for lf in loads:
        if lf.received_at > now:
            break
        spec = spec_for(lf.received_at.date())

        def filled(slot: str, bd: date) -> bool:
            o = occs.get((slot, bd))
            return bool(o and o.loads)

        a = assign_load(lf.received_at, spec, calendar, filled, slot_hints.get(lf.id))
        key = (a.slot_key, a.business_date)
        if key not in occs:
            occs[key] = ReplayOccurrence(a.slot_key, a.business_date, a.expected)
        occs[key].loads.append(lf)

    first_seen: dict[str, datetime] = {}
    for lf in loads:
        first_seen.setdefault(lf.content_hash, lf.received_at)

    history: dict[str, list[HistoryPoint]] = defaultdict(list)
    ordered = sorted(occs.values(), key=lambda o: (o.business_date, o.slot_key))
    for occ in ordered:
        if occ.expected is not None and occ.expected.window_start_utc > now and not occ.loads:
            continue  # future
        spec = spec_for(occ.business_date)
        lookback = occ.business_date - timedelta(days=max(spec.learning.lookback_days, HISTORY_DAYS))
        hist = tuple(p for p in history[occ.slot_key] if p.business_date >= lookback)
        seen = frozenset(lf.content_hash for lf in occ.loads if first_seen[lf.content_hash] < lf.received_at)
        occ.result = engine(
            EvalContext(
                spec=spec,
                calendar=calendar,
                slot_key=occ.slot_key,
                business_date=occ.business_date,
                expected=occ.expected,
                loads=tuple(occ.loads),
                history=hist,
                seen_hashes=seen,
                now=now,
            )
        )
        if occ.slot_key != UNSCHEDULED_SLOT:
            hp = history_point(occ, calendar, labels.get((occ.slot_key, occ.business_date)))
            if hp is not None:
                history[occ.slot_key].append(hp)

    return [o for o in ordered if start <= o.business_date <= end and o.result is not None]
