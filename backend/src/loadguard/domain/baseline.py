"""Robust, explainable baselines for delivery volumes and arrival times.

Model (on log scale, because bill volumes are multiplicative and right-skewed):

    log(y_t) = level + slope * t + phase_effect[month_phase] + weekday_effect[weekday] + e_t

* slope: Theil-Sen estimator (breakdown point ~29%): growth/decline of the biller is not an anomaly.
* effects: median polish with shrinkage, so sparse groups cannot invent seasonality.
* level: median of the *most recent* de-seasonalised points, so a confirmed "new normal" is adopted
  within a handful of deliveries instead of half a lookback window.
* scale: 1.4826 * MAD of residuals with a floor, so ultra-stable billers do not alert on 0.5% noise.
* annual: once a year of history exists, last year's change from "then-recent" to "then-target" is
  applied (seasonal naive drift): heating season, school terms, tax calendars.

Every number is returned so the UI and the advisory AI can say *why* a value was expected.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import numpy as np

from loadguard.domain.calendar import MonthPhase
from loadguard.domain.contract import Sensitivity
from loadguard.domain.model import HistoryPoint

METHOD = "robust-decomposition-v1"
SENSITIVITY_K: dict[Sensitivity, float] = {
    Sensitivity.HIGH: 3.0,
    Sensitivity.MEDIUM: 4.0,
    Sensitivity.LOW: 5.5,
}
MIN_LOG_SCALE = 0.025  # ~2.5% relative noise floor
RECENT_LEVEL_POINTS = 10
MIN_GROUP = 3  # an effect is only estimated from groups with at least this many points
MEDIAN_VAR = math.pi / 2  # variance inflation of a median vs. a mean under normal noise
ANNUAL_WINDOW_DAYS = 10
MAX_ABS_ANNUAL = math.log(3)
MAX_ABS_SLOPE_PER_DAY = math.log(3) / 365  # trends steeper than x3/yr are treated as noise


@dataclass(frozen=True)
class Baseline:
    expected: float
    lower: float
    upper: float
    center_log: float
    scale_log: float
    k: float
    n: int
    method: str = METHOD
    components: dict[str, Any] = field(default_factory=dict)

    def z(self, value: float) -> float:
        return (math.log1p(max(value, 0.0)) - self.center_log) / self.scale_log

    def to_dict(self) -> dict[str, Any]:
        return {
            "expected": self.expected,
            "lower": self.lower,
            "upper": self.upper,
            "scale_log": self.scale_log,
            "k": self.k,
            "n": self.n,
            "method": self.method,
            "components": self.components,
        }


def theil_sen_slope(t: np.ndarray, y: np.ndarray) -> float:
    if len(t) < 3:
        return 0.0
    i, j = np.triu_indices(len(t), k=1)
    dt = t[j] - t[i]
    mask = dt != 0
    if not mask.any():
        return 0.0
    return float(np.median((y[j] - y[i])[mask] / dt[mask]))


def _mad(x: np.ndarray) -> float:
    return float(np.median(np.abs(x - np.median(x)))) if len(x) else 0.0


def _group_effects(keys: list[str], r: np.ndarray) -> tuple[dict[str, float], dict[str, int]]:
    effects: dict[str, float] = {}
    sizes: dict[str, int] = {}
    for key in set(keys):
        idx = [i for i, k in enumerate(keys) if k == key]
        if len(idx) < MIN_GROUP:
            continue
        effects[key] = float(np.median(r[idx]))
        sizes[key] = len(idx)
    return effects, sizes


def volume_baseline(
    history: list[HistoryPoint],
    metric: str,
    *,
    target_date: date,
    target_weekday: int,
    target_phase: MonthPhase,
    sensitivity: Sensitivity,
    min_history: int,
    lookback_days: int = 180,
) -> Baseline | None:
    """Expected value and prediction interval for `metric` on `target_date`. None while still learning."""
    clean = sorted(
        (p for p in history if not p.excluded and metric in p.metrics and p.business_date < target_date),
        key=lambda p: p.business_date,
    )
    pts = [p for p in clean if (target_date - p.business_date).days <= lookback_days]
    if len(pts) < min_history:
        return None

    y = np.array([math.log1p(max(p.metrics[metric], 0.0)) for p in pts])
    t = np.array([(p.business_date - target_date).days for p in pts], dtype=float)
    phases = [p.month_phase.value for p in pts]
    weekdays = [str(p.weekday) for p in pts]

    span = t[-1] - t[0]
    slope = theil_sen_slope(t, y) if len(pts) >= 12 and span >= 45 else 0.0
    slope = max(-MAX_ABS_SLOPE_PER_DAY, min(MAX_ABS_SLOPE_PER_DAY, slope))
    r = y - slope * t

    phase_eff: dict[str, float] = {}
    wd_eff: dict[str, float] = {}
    phase_n: dict[str, int] = {}
    wd_n: dict[str, int] = {}
    for _ in range(3):  # median polish
        base = r - np.array([wd_eff.get(w, 0.0) for w in weekdays])
        phase_eff, phase_n = _group_effects(phases, base - np.median(base))
        base = r - np.array([phase_eff.get(ph, 0.0) for ph in phases])
        wd_eff, wd_n = _group_effects(weekdays, base - np.median(base))

    deseason = r - np.array(
        [phase_eff.get(ph, 0.0) + wd_eff.get(w, 0.0) for ph, w in zip(phases, weekdays, strict=True)]
    )

    # Regime handling: the level comes from the latest regime (recent points), shape from all points.
    regime_idx = max((i for i, p in enumerate(pts) if p.regime_break), default=0)
    post_regime = deseason[regime_idx:]
    recent = post_regime[-RECENT_LEVEL_POINTS:] if len(post_regime) >= 4 else deseason[-RECENT_LEVEL_POINTS:]
    level = float(np.median(recent))

    resid = deseason - float(np.median(deseason))
    n_params = 1 + len(phase_eff) + len(wd_eff) + (1 if slope else 0)
    dof = math.sqrt(len(pts) / max(len(pts) - n_params, 1))
    noise = max(1.4826 * _mad(resid) * dof, MIN_LOG_SCALE)
    # Prediction (not fit) uncertainty: noise + error of the level and of the effects we add.
    var = 1 + MEDIAN_VAR / len(recent)
    tp, tw = target_phase.value, str(target_weekday)
    if tp in phase_n:
        var += MEDIAN_VAR / phase_n[tp]
    if tw in wd_n:
        var += MEDIAN_VAR / wd_n[tw]
    scale = noise * math.sqrt(var)
    k = SENSITIVITY_K[sensitivity]

    annual = (
        _annual_drift(clean, metric, target_date, [p.business_date for p in pts[-RECENT_LEVEL_POINTS:]])
        if regime_idx == 0
        else 0.0
    )
    center = level + annual + phase_eff.get(target_phase.value, 0.0) + wd_eff.get(str(target_weekday), 0.0)
    return Baseline(
        expected=math.expm1(center),
        lower=max(math.expm1(center - k * scale), 0.0),
        upper=math.expm1(center + k * scale),
        center_log=center,
        scale_log=scale,
        k=k,
        n=len(pts),
        components={
            "level": math.expm1(level),
            "trend_per_30d": math.exp(slope * 30),
            "month_phase_factor": math.exp(phase_eff.get(target_phase.value, 0.0)),
            "weekday_factor": math.exp(wd_eff.get(str(target_weekday), 0.0)),
            "month_phase": target_phase.value,
            "weekday": target_weekday,
            "regime_points": int(len(pts) - regime_idx) if regime_idx else None,
            "annual_factor": math.exp(annual),
            "noise_pct": (math.exp(noise) - 1) * 100,
        },
    )


def _annual_drift(clean: list[HistoryPoint], metric: str, target: date, recent_dates: list[date]) -> float:
    """log change last year between the dates now used for the level and the target date (0 if unknown)."""
    if not recent_dates:
        return 0.0

    def window(lo: date, hi: date) -> list[float]:
        return [math.log1p(max(p.metrics[metric], 0.0)) for p in clean if lo <= p.business_date <= hi]

    year = timedelta(days=364)  # same weekday last year
    pad = timedelta(days=ANNUAL_WINDOW_DAYS)
    then_target = window(target - year - pad, target - year + pad)
    then_recent = window(min(recent_dates) - year - pad, max(recent_dates) - year + pad)
    if len(then_target) < 2 or len(then_recent) < 2:
        return 0.0
    drift = float(np.median(then_target) - np.median(then_recent))
    return max(-MAX_ABS_ANNUAL, min(MAX_ABS_ANNUAL, drift))


@dataclass(frozen=True)
class ArrivalProfile:
    median_minutes: float
    p90_minutes: float
    p97_minutes: float
    n: int

    def to_dict(self) -> dict[str, Any]:
        return {"median": self.median_minutes, "p90": self.p90_minutes, "p97": self.p97_minutes, "n": self.n}


def arrival_profile(
    history: list[HistoryPoint], *, target_date: date, min_history: int
) -> ArrivalProfile | None:
    mins = [
        p.first_arrival_minutes
        for p in history
        if p.first_arrival_minutes is not None and not p.excluded and p.business_date < target_date
    ]
    if len(mins) < min_history:
        return None
    arr = np.array(mins[-120:], dtype=float)
    return ArrivalProfile(
        median_minutes=float(np.median(arr)),
        p90_minutes=float(np.quantile(arr, 0.90)),
        p97_minutes=float(np.quantile(arr, 0.97)),
        n=len(arr),
    )
