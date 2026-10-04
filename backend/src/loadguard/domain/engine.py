"""Evaluate one occurrence: the single, pure entry point used by live runs, replays and backtests."""

from __future__ import annotations

import statistics
from dataclasses import dataclass, replace
from typing import Any

from loadguard.domain.baseline import arrival_profile
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.detectors.limits import detect_limits
from loadguard.domain.detectors.quality import detect_quality
from loadguard.domain.detectors.timeliness import detect_timeliness
from loadguard.domain.detectors.volume import compute_baselines, detect_volume
from loadguard.domain.model import Finding, HistoryPoint, OccurrenceStatus, aggregate_metrics
from loadguard.domain.schedule import local_minutes

ENGINE_VERSION = "engine-2.0.0"


@dataclass(frozen=True)
class EvalResult:
    status: OccurrenceStatus
    findings: list[Finding]
    metrics: dict[str, float]
    baselines: dict[str, Any]
    first_arrival_minutes: int | None
    engine_version: str = ENGINE_VERSION

    @property
    def max_severity(self) -> str | None:
        if not self.findings:
            return None
        return max(self.findings, key=lambda f: f.severity.rank).severity.value


def reference_metrics(history: list[HistoryPoint], n: int = 10) -> dict[str, float]:
    """Median of recent clean deliveries: used for impact estimates even while baselines are learning."""
    pts = [p for p in history if p.metrics and not p.excluded][-n:]
    if not pts:
        return {}
    keys = {"record_count", "total_amount", "customer_count"}
    return {k: float(statistics.median(p.metrics[k] for p in pts if k in p.metrics)) for k in keys}


def evaluate(ctx: EvalContext) -> EvalResult:
    loads = tuple(sorted(ctx.loads, key=lambda lf: lf.received_at))
    ctx = replace(ctx, loads=loads, metrics=aggregate_metrics(list(loads)))
    min_hist = ctx.spec.learning.min_history

    arrival = arrival_profile(list(ctx.history), target_date=ctx.business_date, min_history=min_hist)
    status, findings = detect_timeliness(ctx, arrival)

    baselines_out: dict[str, Any] = {
        "arrival": arrival.to_dict() if arrival else None,
        "reference": reference_metrics(list(ctx.history)),
    }
    if ctx.expected is not None:
        baselines = compute_baselines(ctx)
        for metric, b in baselines.items():
            baselines_out[metric] = (
                b.to_dict() if b else {"status": "LEARNING", "n": len(ctx.history), "needed": min_hist}
            )
        if loads:
            quality = detect_quality(ctx)
            findings += quality
            # Root-cause consolidation: a unit-scale error explains amount deviations; don't double-report.
            skip = (
                {"total_amount", "avg_amount"}
                if any(f.code == "UNIT_SCALE_SUSPECT" for f in quality)
                else set()
            )
            if any(f.code in ("DUPLICATE_FILE", "STALE_DATA") for f in quality):
                skip |= {"record_count", "total_amount", "customer_count", "avg_amount"}
            findings += detect_volume(ctx, baselines, skip_metrics=skip)
            findings += detect_limits(ctx)
    elif loads:
        # Content checks apply to every file, scheduled or not (history-based ones simply have no history).
        findings += detect_quality(ctx)
        findings += detect_limits(ctx)

    return EvalResult(
        status=status,
        findings=findings,
        metrics=ctx.metrics,
        baselines=baselines_out,
        first_arrival_minutes=local_minutes(loads[0].received_at, ctx.spec.timezone) if loads else None,
    )
