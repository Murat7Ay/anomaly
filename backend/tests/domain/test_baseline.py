from __future__ import annotations

import math
import random
from datetime import date

from loadguard.domain.baseline import theil_sen_slope, volume_baseline
from loadguard.domain.calendar import MonthPhase
from loadguard.domain.contract import Sensitivity
from loadguard.domain.model import HistoryPoint

from .conftest import business_days


def _points(cal, days, value_fn, **kw):
    return [
        HistoryPoint(d, d.isoweekday(), cal.month_phase(d), {"record_count": value_fn(i, d)}, 450, **kw)
        for i, d in enumerate(days)
    ]


def _bl(cal, pts, target, sens=Sensitivity.MEDIUM):
    return volume_baseline(
        pts,
        "record_count",
        target_date=target,
        target_weekday=target.isoweekday(),
        target_phase=cal.month_phase(target),
        sensitivity=sens,
        min_history=8,
    )


def test_learning_until_min_history(cal):
    days = business_days(cal, date(2026, 6, 1), 5)
    assert _bl(cal, _points(cal, days, lambda i, d: 1000.0), date(2026, 6, 30)) is None


def test_learns_month_start_peak(cal):
    rng = random.Random(1)
    days = business_days(cal, date(2026, 1, 5), 150)
    pts = _points(
        cal,
        days[:-1],
        lambda i, d: (
            100_000 * (1.6 if cal.month_phase(d) == MonthPhase.START else 1.0) * math.exp(rng.gauss(0, 0.04))
        ),
    )
    target = date(2026, 8, 3)  # first business day of August
    b = _bl(cal, [p for p in pts if p.business_date < target], target)
    assert b is not None
    assert 145_000 < b.expected < 175_000
    assert b.components["month_phase_factor"] > 1.4


def test_robust_to_outliers_in_history(cal):
    days = business_days(cal, date(2026, 3, 2), 80)
    pts = _points(cal, days, lambda i, d: 50_000.0 * (5 if i % 15 == 0 else 1) * (1 + 0.01 * (i % 3)))
    b = _bl(cal, pts, date(2026, 7, 1))
    assert b is not None and 45_000 < b.expected < 56_000


def test_follows_growth_trend(cal):
    days = business_days(cal, date(2025, 10, 1), 160)
    pts = _points(cal, days, lambda i, d: 20_000.0 * math.exp(0.004 * (d - days[0]).days))
    target = cal.next_business_day(days[-1])
    b = _bl(cal, pts, target)
    naive = 20_000 * math.exp(0.004 * (target - days[0]).days)
    assert b is not None and abs(b.expected / naive - 1) < 0.05
    assert b.components["trend_per_30d"] > 1.08


def test_regime_break_adopts_new_normal_quickly(cal):
    days = business_days(cal, date(2026, 1, 5), 140)
    shift_at = 120
    pts = _points(cal, days, lambda i, d: 10_000.0 * (1.3 if i >= shift_at else 1.0) * (1 + 0.005 * (i % 4)))
    pts[shift_at] = HistoryPoint(**{**pts[shift_at].__dict__, "regime_break": True})
    b = _bl(cal, pts, cal.next_business_day(days[-1]))
    assert b is not None and b.expected > 12_500


def test_excluded_points_are_not_learned(cal):
    days = business_days(cal, date(2026, 3, 2), 40)
    pts = _points(cal, days, lambda i, d: 1_000.0 if i < 30 else 50.0)
    pts = [HistoryPoint(**{**p.__dict__, "excluded": i >= 30}) for i, p in enumerate(pts)]
    b = _bl(cal, pts, date(2026, 6, 1))
    assert b is not None and b.expected > 900


def test_sensitivity_controls_band_width(cal):
    rng = random.Random(3)
    days = business_days(cal, date(2026, 1, 5), 100)
    pts = _points(cal, days, lambda i, d: 30_000 * math.exp(rng.gauss(0, 0.05)))
    hi = _bl(cal, pts, date(2026, 7, 1), Sensitivity.HIGH)
    lo = _bl(cal, pts, date(2026, 7, 1), Sensitivity.LOW)
    assert hi and lo and (hi.upper - hi.lower) < (lo.upper - lo.lower)


def test_theil_sen_ignores_outliers():
    import numpy as np

    t = np.arange(30, dtype=float)
    y = 2 * t
    y[5] = 500
    assert abs(theil_sen_slope(t, y) - 2) < 1e-9
