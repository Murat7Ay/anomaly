"""Volume deviations against the learned, seasonality-aware baseline."""

from __future__ import annotations

from typing import Any

from loadguard.domain import fmt
from loadguard.domain.baseline import Baseline, volume_baseline
from loadguard.domain.contract import Direction, Severity
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.model import Category, Finding

CRITICAL_LOW_RATIO = 0.5
CRITICAL_HIGH_RATIO = 2.0


def compute_baselines(ctx: EvalContext) -> dict[str, Baseline | None]:
    phase = ctx.calendar.month_phase(ctx.business_date)
    return {
        w.metric.value: volume_baseline(
            list(ctx.history),
            w.metric.value,
            target_date=ctx.business_date,
            target_weekday=ctx.business_date.isoweekday(),
            target_phase=phase,
            sensitivity=w.sensitivity,
            min_history=ctx.spec.learning.min_history,
            lookback_days=ctx.spec.learning.lookback_days,
        )
        for w in ctx.spec.metrics
    }


def _explain(b: Baseline) -> str:
    c = b.components
    parts = [f"son {b.n} benzer teslimattan öğrenilen seviye {fmt.num(c['level'])}"]
    if abs(c["month_phase_factor"] - 1) >= 0.05:
        phase = {"START": "ay başı", "MID": "ay ortası", "END": "ay sonu"}[c["month_phase"]]
        parts.append(f"{phase} etkisi x{fmt.num(c['month_phase_factor'], 2)}")
    if abs(c["weekday_factor"] - 1) >= 0.05:
        parts.append(f"haftanın günü etkisi x{fmt.num(c['weekday_factor'], 2)}")
    if abs(c.get("annual_factor", 1) - 1) >= 0.05:
        parts.append(f"geçen yılın mevsimsel değişimi x{fmt.num(c['annual_factor'], 2)}")
    if abs(c["trend_per_30d"] - 1) >= 0.01:
        parts.append(f"aylık eğilim x{fmt.num(c['trend_per_30d'], 3)}")
    return "; ".join(parts)


def detect_volume(
    ctx: EvalContext, baselines: dict[str, Baseline | None], *, skip_metrics: set[str]
) -> list[Finding]:
    out: list[Finding] = []
    for w in ctx.spec.metrics:
        metric = w.metric.value
        b = baselines.get(metric)
        if b is None or metric in skip_metrics or metric not in ctx.metrics:
            continue
        obs = ctx.metrics[metric]
        z = b.z(obs)
        low = z < -b.k and w.direction != Direction.HIGH_ONLY
        high = z > b.k and w.direction != Direction.LOW_ONLY
        if not (low or high):
            continue
        ratio = obs / b.expected if b.expected else float("inf")
        critical = (low and ratio < CRITICAL_LOW_RATIO) or (high and ratio > CRITICAL_HIGH_RATIO)
        change = (ratio - 1) * 100
        word = "düşük" if low else "yüksek"
        ev: dict[str, Any] = {
            "baseline": b.to_dict(),
            "z": z,
            "ratio": ratio,
            "sensitivity": w.sensitivity.value,
        }
        out.append(
            Finding(
                code="VOLUME_LOW" if low else "VOLUME_HIGH",
                category=Category.VOLUME,
                severity=Severity.CRITICAL if critical else Severity.WARNING,
                message=(
                    f"{fmt.METRIC_LABELS[metric]} beklenenden %{fmt.num(abs(change))} {word}: "
                    f"{fmt.metric_value(metric, obs)} (beklenen {fmt.metric_value(metric, b.expected)}, "
                    f"olağan aralık {fmt.metric_value(metric, b.lower)} – {fmt.metric_value(metric, b.upper)}). "
                    f"Dayanak: {_explain(b)}."
                    + (" Kısmi dosya olabilir; tamamlayıcı dosya beklenebilir." if low else "")
                ),
                metric=metric,
                observed=obs,
                expected=b.expected,
                lower=b.lower,
                upper=b.upper,
                score=z,
                evidence=ev,
            )
        )
    return out
