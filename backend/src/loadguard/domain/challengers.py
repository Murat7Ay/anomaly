"""Challenger models evaluated in shadow mode next to the champion engine.

A challenger never pages anyone. Its decisions are stored per occurrence and compared with the
champion and with analyst verdicts (services.analytics.shadow_report). It is promoted only when it
earns it on real data, through a normal code change that passes the quality gate. This is how the
detection logic can evolve for a decade without ever being changed blind.

Register: CHALLENGERS["name-vN"] = callable(EvalContext) -> EvalResult. Names are immutable once
results are stored; a changed algorithm gets a new version suffix.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

from loadguard.domain import fmt
from loadguard.domain.baseline import volume_baseline
from loadguard.domain.contract import Sensitivity, Severity
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.engine import EvalResult, evaluate
from loadguard.domain.model import Category, Finding, HistoryPoint, aggregate_metrics

RATIOS: dict[str, tuple[str, str, str]] = {
    # name: (numerator, denominator, label)
    "records_per_customer": ("record_count", "customer_count", "Müşteri başına kayıt"),
    "amount_per_record": ("total_amount", "record_count", "Kayıt başına tutar"),
}


def _with_ratios(p: HistoryPoint) -> HistoryPoint:
    m = dict(p.metrics)
    for name, (num, den, _) in RATIOS.items():
        if m.get(den):
            m[name] = m.get(num, 0.0) / m[den]
    return replace(p, metrics=m)


def detect_mix_shift(ctx: EvalContext, ratios: tuple[str, ...] = tuple(RATIOS)) -> list[Finding]:
    """Composition change while totals look normal (e.g. one subscriber segment silently dropped)."""
    if ctx.expected is None or not ctx.loads:
        return []
    m = aggregate_metrics(list(ctx.loads))
    hist = [_with_ratios(p) for p in ctx.history]
    out: list[Finding] = []
    for name in ratios:
        num, den, label = RATIOS[name]
        if not m.get(den):
            continue
        obs = m.get(num, 0.0) / m[den]
        b = volume_baseline(
            hist,
            name,
            target_date=ctx.business_date,
            target_weekday=ctx.business_date.isoweekday(),
            target_phase=ctx.calendar.month_phase(ctx.business_date),
            sensitivity=Sensitivity.MEDIUM,
            min_history=ctx.spec.learning.min_history,
            lookback_days=ctx.spec.learning.lookback_days,
        )
        if b is None:
            continue
        z = b.z(obs)
        if abs(z) <= b.k:
            continue
        out.append(
            Finding(
                code="MIX_SHIFT",
                category=Category.VOLUME,
                severity=Severity.WARNING,
                message=(
                    f"{label} olağan dışı: {fmt.num(obs, 3)} (beklenen {fmt.num(b.expected, 3)}, "
                    f"aralık {fmt.num(b.lower, 3)}–{fmt.num(b.upper, 3)}). Toplamlar normal görünse de "
                    "dosyanın bileşimi değişmiş olabilir (eksik/yeni segment)."
                ),
                metric=name,
                observed=obs,
                expected=b.expected,
                lower=b.lower,
                upper=b.upper,
                score=z,
                evidence={"baseline": b.to_dict()},
            )
        )
    return out


def mix_shift_v1(ctx: EvalContext) -> EvalResult:
    base = evaluate(ctx)
    extra = detect_mix_shift(ctx)
    return replace(base, findings=base.findings + extra, engine_version=f"{base.engine_version}+mix-shift-v1")


def mix_shift_v2(ctx: EvalContext) -> EvalResult:
    """v1 minus amount_per_record: shadow data showed that ratio is seasonal (heating) and noisy."""
    base = evaluate(ctx)
    extra = detect_mix_shift(ctx, ratios=("records_per_customer",))
    return replace(base, findings=base.findings + extra, engine_version=f"{base.engine_version}+mix-shift-v2")


CHALLENGERS: dict[str, Callable[[EvalContext], EvalResult]] = {
    "mix-shift-v1": mix_shift_v1,  # kept for the record: +recall, but too many seasonal false alarms
    "mix-shift-v2": mix_shift_v2,
}
