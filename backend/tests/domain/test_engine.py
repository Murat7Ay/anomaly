from __future__ import annotations

from datetime import date, timedelta

import pytest

from loadguard.domain.contract import UNSCHEDULED_SLOT, HardLimit, LimitMetric, Severity
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.engine import evaluate
from loadguard.domain.matching import assign_load
from loadguard.domain.model import HistoryPoint, OccurrenceStatus
from loadguard.domain.schedule import expected_occurrences
from loadguard.domain.triage import Impact, Priority, estimate_impact, priority_for

from .conftest import at, business_days, load

TARGET = date(2026, 9, 16)  # Wednesday, mid-month


def _history(cal, n=40, records=100_000, avg=500.0, arrival=7 * 60 + 30):
    days = [d for d in business_days(cal, TARGET - timedelta(days=80), 200) if d < TARGET][-n:]
    return tuple(
        HistoryPoint(
            d,
            d.isoweekday(),
            cal.month_phase(d),
            {
                "record_count": records * (1 + 0.01 * (i % 5 - 2)),
                "total_amount": records * avg * (1 + 0.01 * (i % 5 - 2)),
                "customer_count": records * 0.95,
                "avg_amount": avg,
            },
            arrival + (i % 7) * 3,
        )
        for i, d in enumerate(days)
    )


def _ctx(cal, spec, loads, now, history=None, seen=frozenset(), expected=True):
    occ = expected_occurrences(spec, cal, TARGET, TARGET)[0] if expected else None
    return EvalContext(
        spec=spec,
        calendar=cal,
        slot_key="daily" if expected else UNSCHEDULED_SLOT,
        business_date=TARGET,
        expected=occ,
        loads=tuple(loads),
        history=history if history is not None else _history(cal),
        seen_hashes=seen,
        now=now,
    )


def codes(res):
    return {f.code for f in res.findings}


def test_normal_delivery_is_quiet(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [load(TARGET, 7, 40)], at(TARGET, 12)))
    assert res.status == OccurrenceStatus.RECEIVED
    assert res.findings == []
    assert res.baselines["record_count"]["expected"] == pytest.approx(100_000, rel=0.03)


def test_missing_after_deadline_is_critical(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [], at(TARGET, 10, 1)))
    assert res.status == OccurrenceStatus.MISSING
    assert codes(res) == {"MISSING_DELIVERY"}
    assert res.findings[0].severity == Severity.CRITICAL


def test_at_risk_before_deadline_when_later_than_usual(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [], at(TARGET, 8, 30)))
    assert res.status == OccurrenceStatus.AT_RISK
    assert codes(res) == {"DELIVERY_AT_RISK"}


def test_pending_while_within_usual_time(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [], at(TARGET, 7, 0)))
    assert res.status == OccurrenceStatus.PENDING and not res.findings


def test_late_delivery(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [load(TARGET, 11, 30)], at(TARGET, 12)))
    assert res.status == OccurrenceStatus.LATE
    f = next(f for f in res.findings if f.code == "LATE_DELIVERY")
    assert f.severity == Severity.WARNING and f.observed == pytest.approx(90, abs=1)


def test_partial_file_flags_low_volume(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [load(TARGET, 7, 40, records=40_000)], at(TARGET, 12)))
    low = [f for f in res.findings if f.code == "VOLUME_LOW"]
    assert {f.metric for f in low} == {"record_count", "total_amount"}
    assert all(f.severity == Severity.CRITICAL for f in low)  # < 50% of expected


def test_complementary_file_clears_low_volume(cal, daily_spec):
    parts = [load(TARGET, 7, 40, records=40_000), load(TARGET, 8, 50, records=60_000)]
    res = evaluate(_ctx(cal, daily_spec, parts, at(TARGET, 12)))
    assert "VOLUME_LOW" not in codes(res)


def test_unit_scale_error_is_root_caused(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [load(TARGET, 7, 40, avg=50_000.0)], at(TARGET, 12)))
    assert "UNIT_SCALE_SUSPECT" in codes(res)
    assert not any(f.code == "VOLUME_HIGH" and f.metric == "total_amount" for f in res.findings)


def test_duplicate_file(cal, daily_spec):
    lf = load(TARGET, 7, 40)
    res = evaluate(_ctx(cal, daily_spec, [lf], at(TARGET, 12), seen=frozenset({lf.content_hash})))
    assert "DUPLICATE_FILE" in codes(res)


def test_stale_data(cal, daily_spec):
    hist = _history(cal)
    last = hist[-1].metrics
    lf = load(
        TARGET,
        7,
        40,
        records=int(last["record_count"]),
        total_amount=last["total_amount"],
        customer_count=last["customer_count"],
    )
    hist = (
        *hist[:-1],
        HistoryPoint(
            **{
                **hist[-1].__dict__,
                "metrics": {
                    **last,
                    "record_count": float(lf.record_count),
                    "customer_count": float(lf.customer_count),
                },
            }
        ),
    )
    res = evaluate(_ctx(cal, daily_spec, [lf], at(TARGET, 12), history=hist))
    assert "STALE_DATA" in codes(res)


def test_quality_rules(cal, daily_spec):
    res = evaluate(
        _ctx(
            cal,
            daily_spec,
            [load(TARGET, 7, 40, zero_amount_count=30_000, negative_amount_count=4)],
            at(TARGET, 12),
        )
    )
    assert {"ZERO_AMOUNT_RECORDS", "NEGATIVE_AMOUNTS"} <= codes(res)


def test_hard_limit(cal, daily_spec):
    spec = daily_spec.model_copy(
        update={"limits": [HardLimit(id="cap", metric=LimitMetric.RECORD_COUNT, max=90_000)]}
    )
    res = evaluate(_ctx(cal, spec, [load(TARGET, 7, 40)], at(TARGET, 12)))
    assert "LIMIT_BREACH" in codes(res)


def test_unexpected_delivery_is_info_by_default(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [load(TARGET, 7, 40)], at(TARGET, 12), expected=False))
    assert res.status == OccurrenceStatus.UNSCHEDULED
    assert [f.severity for f in res.findings] == [Severity.INFO]


def test_learning_phase_has_no_volume_findings(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [load(TARGET, 7, 40, records=10)], at(TARGET, 12), history=()))
    assert not [f for f in res.findings if f.category.value == "VOLUME"]
    assert res.baselines["record_count"]["status"] == "LEARNING"


def test_assignment_prefers_on_time_then_late_then_unscheduled(cal, daily_spec):
    filled: set[tuple[str, date]] = set()

    def is_filled(k, d):
        return (k, d) in filled

    a = assign_load(at(TARGET, 7), daily_spec, cal, is_filled)
    assert (a.slot_key, a.business_date, a.reason) == ("daily", TARGET, "ON_TIME")
    filled.add(("daily", TARGET))
    assert assign_load(at(TARGET, 9), daily_spec, cal, is_filled).reason == "ADDITIONAL"
    sat = date(2026, 9, 19)
    b = assign_load(at(sat, 9), daily_spec, cal, is_filled)
    assert b.reason == "LATE" and b.business_date == date(2026, 9, 18)
    filled.add(("daily", date(2026, 9, 18)))
    filled.add(("daily", date(2026, 9, 17)))
    filled.add(("daily", date(2026, 9, 15)))
    assert assign_load(at(sat, 9), daily_spec, cal, is_filled).slot_key == UNSCHEDULED_SLOT


def test_priority_combines_severity_tier_and_impact():
    small = Impact(1_000, 1e5, "x")
    big = Impact(120_000, 1e8, "x")
    assert priority_for(Severity.CRITICAL, 1, small) == Priority.P1
    assert priority_for(Severity.CRITICAL, 3, small) == Priority.P2
    assert priority_for(Severity.CRITICAL, 3, big) == Priority.P1
    assert priority_for(Severity.WARNING, 1, big) == Priority.P2
    assert priority_for(Severity.WARNING, 2, big) == Priority.P3


def test_missing_impact_uses_reference(cal, daily_spec):
    res = evaluate(_ctx(cal, daily_spec, [], at(TARGET, 11)))
    imp = estimate_impact(res.findings, res.metrics, res.baselines["reference"])
    assert imp.customers == pytest.approx(95_000, rel=0.05)


def test_unscheduled_delivery_still_gets_content_checks(cal, daily_spec):
    res = evaluate(
        _ctx(cal, daily_spec, [load(TARGET, 7, 40, negative_amount_count=12)], at(TARGET, 12), expected=False)
    )
    assert {"UNEXPECTED_DELIVERY", "NEGATIVE_AMOUNTS"} <= codes(res)
