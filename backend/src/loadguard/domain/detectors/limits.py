"""Deterministic hard limits owned by the business (e.g. 'never more than 2M records')."""

from __future__ import annotations

from loadguard.domain import fmt
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.model import Category, Finding


def detect_limits(ctx: EvalContext) -> list[Finding]:
    out: list[Finding] = []
    if not ctx.loads:
        return out
    for lim in ctx.spec.limits:
        v = ctx.metrics.get(lim.metric.value)
        if v is None:
            continue
        below = lim.min is not None and v < lim.min
        above = lim.max is not None and v > lim.max
        if not (below or above):
            continue
        bound = lim.min if below else lim.max
        assert bound is not None
        label = fmt.METRIC_LABELS.get(lim.metric.value, lim.metric.value)
        out.append(
            Finding(
                code="LIMIT_BREACH",
                category=Category.RULE,
                severity=lim.severity,
                message=(
                    f"Kural '{lim.id}': {label} {fmt.metric_value(lim.metric.value, v)}, "
                    f"{'alt' if below else 'üst'} sınır {fmt.metric_value(lim.metric.value, bound)}."
                    + (f" ({lim.note})" if lim.note else "")
                ),
                metric=lim.metric.value,
                observed=v,
                lower=lim.min,
                upper=lim.max,
                evidence={"limit_id": lim.id},
            )
        )
    return out
