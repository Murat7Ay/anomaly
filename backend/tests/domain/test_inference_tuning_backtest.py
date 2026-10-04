from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

from loadguard.domain.backtest import Verdict, run_backtest
from loadguard.domain.contract import Cadence, Sensitivity
from loadguard.domain.inference import infer_contract
from loadguard.domain.tuning import ResolvedFinding, suggest_tuning
from loadguard.sim.simulator import default_archetypes, simulate_institution


def _arch(code):
    return next(a for a in default_archetypes() if a.code == code)


def test_infers_business_day_cadence_and_window(cal):
    a = _arch("ELK01")
    loads, _ = simulate_institution(a, cal, date(2026, 3, 1), date(2026, 8, 31), seed=1)
    inf = infer_contract(
        [s.facts.received_at for s in loads], cal, start=date(2026, 3, 1), end=date(2026, 8, 31)
    )
    assert inf.spec is not None
    slot = inf.spec.slots[0]
    assert slot.cadence == Cadence.BUSINESS_DAYS
    assert slot.window_start <= time(7) and time(8) <= slot.deadline <= time(10)
    assert inf.confidence > 0.9


def test_infers_monthly_days(cal):
    a = _arch("SU01")
    loads, _ = simulate_institution(a, cal, date(2025, 9, 1), date(2026, 8, 31), seed=1)
    inf = infer_contract(
        [s.facts.received_at for s in loads], cal, start=date(2025, 9, 1), end=date(2026, 8, 31)
    )
    assert inf.spec is not None
    assert inf.spec.slots[0].cadence == Cadence.MONTHLY
    assert inf.spec.slots[0].month_days == [5, 20]


def test_infers_weekly(cal):
    a = _arch("NET01")
    loads, _ = simulate_institution(a, cal, date(2026, 2, 1), date(2026, 8, 31), seed=1)
    inf = infer_contract(
        [s.facts.received_at for s in loads], cal, start=date(2026, 2, 1), end=date(2026, 8, 31)
    )
    assert inf.spec is not None and inf.spec.slots[0].weekdays == [1, 4]


def test_tuning_lowers_sensitivity_after_repeated_false_alarms():
    spec = _arch("GAZ02").spec
    assert spec.metrics[0].sensitivity == Sensitivity.HIGH
    fps = [
        ResolvedFinding("VOLUME_HIGH", "record_count", "daily", "FALSE_POSITIVE", 1.0, {}) for _ in range(4)
    ]
    tp = [ResolvedFinding("VOLUME_LOW", "record_count", "daily", "TRUE_POSITIVE", 1.0, {})]
    sug = suggest_tuning(spec, fps + tp)
    assert len(sug) == 1
    assert sug[0].proposed.metrics[0].sensitivity == Sensitivity.MEDIUM


def test_tuning_moves_deadline_to_observed_arrivals():
    spec = _arch("ELK01").spec
    items = [
        ResolvedFinding("LATE_DELIVERY", None, "daily", "FALSE_POSITIVE", 20.0, {"arrived": f"10:{m:02d}"})
        for m in (10, 20, 25, 40)
    ]
    sug = suggest_tuning(spec, items)
    assert sug and sug[0].proposed.slots[0].deadline == time(11, 0)


def test_tuning_ignores_mixed_evidence():
    spec = _arch("ELK01").spec
    items = [
        ResolvedFinding("VOLUME_LOW", "record_count", "daily", r, 1.0, {})
        for r in ["FALSE_POSITIVE"] * 3 + ["TRUE_POSITIVE"] * 3
    ]
    assert suggest_tuning(spec, items) == []


def test_backtest_compares_candidate_against_current(cal):
    a = _arch("BLD01")
    start, end = date(2025, 10, 1), date(2026, 8, 31)
    loads, _ = simulate_institution(a, cal, start, end, seed=7)
    relaxed = a.spec.model_copy(
        update={"metrics": [m.model_copy(update={"sensitivity": Sensitivity.LOW}) for m in a.spec.metrics]}
    )
    rep = run_backtest(
        candidate=relaxed,
        current=a.spec,
        calendar=cal,
        loads=[s.facts for s in loads],
        start=end - timedelta(days=150),
        end=end,
        now=datetime(2026, 9, 1, tzinfo=UTC),
        history_labels={},
        verdicts=[Verdict("daily", end, "VOLUME", "TRUE_POSITIVE")],
    )
    assert rep["candidate"]["alerting_occurrences"] <= rep["current"]["alerting_occurrences"]
    assert rep["verdicts"]["true_positive_total"] == 1
