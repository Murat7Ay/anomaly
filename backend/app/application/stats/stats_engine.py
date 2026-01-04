from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from app.application.calendar_service import CalendarWindow
from app.domain.enums import Severity
from app.domain.profile.config import InstitutionProfileConfig, StatsMethod, VolumeBehavior
from app.domain.profile.schedule_resolver import ScheduleResolver


def _parse_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _select_windows(preferred: int) -> list[int]:
    if preferred == 3:
        return [3, 6, 9, 12]
    if preferred == 6:
        return [6, 9, 12]
    if preferred == 9:
        return [9, 12]
    return [12]


@dataclass(frozen=True)
class StatsSignal:
    layer: str  # "STATS"
    signal_type: str
    metric_id: str | None
    occurrence_id: str | None
    is_triggered: bool
    severity_suggested: str  # "WARNING" | "CRITICAL"
    score: Decimal | None
    threshold_low: Decimal | None
    threshold_high: Decimal | None
    explanation_json: dict[str, Any]


class StatsEngineV1:
    """
    Statistical analysis layer.

    - Uses profile distributions (3/6/9/12m) computed on expected days only
    - Evaluates volume and timing independently
    """

    def __init__(self, *, schedule_resolver: ScheduleResolver) -> None:
        self._resolver = schedule_resolver

    def evaluate(
        self,
        *,
        profile: InstitutionProfileConfig,
        as_of_date: date,
        run_type: str,
        daily_aggregate: Mapping[str, Any],
        calendar_window: CalendarWindow,
        stats_snapshot_json: dict[str, Any],
    ) -> list[dict[str, Any]]:
        # Determine which runs to evaluate: PM run also checks AM expectations (late/missed AM loads).
        runs = ["AM_0900"] if run_type == "AM_0900" else ["AM_0900", "PM_1400"] if run_type == "PM_1400" else [run_type]

        # Expected occurrences for the day
        expected_by_date = self._resolver.expected_by_date(
            schedule=profile.schedule, window=calendar_window, start_date=as_of_date, end_date=as_of_date
        )
        occs_today = expected_by_date.get(as_of_date, [])

        has_load = bool(daily_aggregate.get("has_load", False))
        earliest_minutes = daily_aggregate.get("earliest_received_minutes")
        metrics: Mapping[str, Decimal] = daily_aggregate.get("metrics", {})

        signals: list[StatsSignal] = []

        # Timing & no-data signals are per-run against expected_by_run occurrences
        for run in runs:
            occs_run = [o for o in occs_today if o.expected_by_run == run]
            if not occs_run:
                continue  # not expected for this run

            # NO_DATA: expected but no load present at evaluation time
            if not has_load:
                sev = "CRITICAL" if run_type == "PM_1400" else "WARNING"
                signals.append(
                    StatsSignal(
                        layer="STATS",
                        signal_type="NO_DATA",
                        metric_id=None,
                        occurrence_id=occs_run[0].occurrence_id if len(occs_run) == 1 else None,
                        is_triggered=True,
                        severity_suggested=sev,
                        score=None,
                        threshold_low=None,
                        threshold_high=None,
                        explanation_json={
                            "reason": "expected_but_no_load_present",
                            "evaluated_run": run,
                            "run_type": run_type,
                            "expected_occurrences": [o.__dict__ for o in occs_run],
                        },
                    )
                )
                continue

            # Timing anomalies (EARLY/LATE) only if we have arrival time
            if earliest_minutes is not None:
                timing_sig = self._timing_signal(
                    profile=profile,
                    occs_run=occs_run,
                    earliest_minutes=int(earliest_minutes),
                    stats_snapshot_json=stats_snapshot_json,
                )
                if timing_sig is not None:
                    signals.append(timing_sig)

        # Volume anomalies are evaluated once per day (on expected day), using the first matching occurrence.
        if has_load and occs_today:
            # Determine occurrence segment
            occurrence_id = occs_today[0].occurrence_id if len(occs_today) == 1 else "__COLLISION__"
            for vm in profile.volume_models:
                v = metrics.get(vm.metric_id)
                if v is None:
                    continue
                sig = self._volume_signal(
                    metric_id=vm.metric_id,
                    value=v,
                    behavior=vm.behavior,
                    segment=occurrence_id if vm.segment_by_occurrence else "__ALL__",
                    method=vm.method_policy.primary_method,
                    method_params=vm.method_policy.params,
                    preferred_window=vm.method_policy.window_months,
                    min_n=vm.method_policy.min_n,
                    fallback_order=vm.method_policy.fallback_order,
                    stats_snapshot_json=stats_snapshot_json,
                )
                if sig is not None:
                    signals.append(sig)

        # Convert to dicts expected by persistence layer
        return [
            {
                "layer": s.layer,
                "signal_type": s.signal_type,
                "metric_id": s.metric_id,
                "occurrence_id": s.occurrence_id,
                "is_triggered": s.is_triggered,
                "severity_suggested": s.severity_suggested,
                "score": s.score,
                "threshold_low": s.threshold_low,
                "threshold_high": s.threshold_high,
                "explanation_json": s.explanation_json,
            }
            for s in signals
        ]

    def _timing_signal(
        self,
        *,
        profile: InstitutionProfileConfig,
        occs_run: list,
        earliest_minutes: int,
        stats_snapshot_json: dict[str, Any],
    ) -> StatsSignal | None:
        # Use 6m timing distribution by default; fall back to 12m if missing.
        for months in (6, 12):
            w = stats_snapshot_json.get("windows", {}).get(str(months), {})
            timing = w.get("timing", {}).get("segments", {})
            seg = occs_run[0].occurrence_id if len(occs_run) == 1 else "__ALL__"
            stats = timing.get(seg) or timing.get("__ALL__")
            if not stats:
                continue
            n = int(stats.get("n", 0))
            if n < 12:
                continue
            p05 = _parse_decimal(stats.get("p05"))
            p95 = _parse_decimal(stats.get("p95"))
            if p05 is None or p95 is None:
                continue

            val = Decimal(earliest_minutes)
            if val < p05:
                delta = p05 - val
                sev = "CRITICAL" if delta >= 60 else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="EARLY_LOAD",
                    metric_id=None,
                    occurrence_id=seg if seg != "__ALL__" else None,
                    is_triggered=True,
                    severity_suggested=sev,
                    score=None,
                    threshold_low=p05,
                    threshold_high=p95,
                    explanation_json={
                        "method": "PERCENTILE_BAND",
                        "window_months": months,
                        "segment": seg,
                        "n": n,
                        "value_minutes": int(earliest_minutes),
                        "p05_minutes": str(p05),
                        "p95_minutes": str(p95),
                        "delta_minutes": str(delta),
                    },
                )
            if val > p95:
                delta = val - p95
                sev = "CRITICAL" if delta >= 60 else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="LATE_LOAD",
                    metric_id=None,
                    occurrence_id=seg if seg != "__ALL__" else None,
                    is_triggered=True,
                    severity_suggested=sev,
                    score=None,
                    threshold_low=p05,
                    threshold_high=p95,
                    explanation_json={
                        "method": "PERCENTILE_BAND",
                        "window_months": months,
                        "segment": seg,
                        "n": n,
                        "value_minutes": int(earliest_minutes),
                        "p05_minutes": str(p05),
                        "p95_minutes": str(p95),
                        "delta_minutes": str(delta),
                    },
                )
            return None
        return None

    def _volume_signal(
        self,
        *,
        metric_id: str,
        value: Decimal,
        behavior: VolumeBehavior,
        segment: str,
        method: StatsMethod,
        method_params: dict[str, Any],
        preferred_window: int,
        min_n: int,
        fallback_order: list[StatsMethod],
        stats_snapshot_json: dict[str, Any],
    ) -> StatsSignal | None:
        # Try preferred window, then larger windows if needed.
        window_candidates = _select_windows(int(preferred_window))

        def get_stats(months: int) -> tuple[int, dict[str, Any]] | None:
            w = stats_snapshot_json.get("windows", {}).get(str(months), {})
            metric_block = w.get("metrics", {}).get(metric_id, {})
            segs = metric_block.get("segments", {})
            st = segs.get(segment) or segs.get("__ALL__")
            if not st:
                return None
            return int(st.get("n", 0)), st

        chosen_months: int | None = None
        chosen_stats: dict[str, Any] | None = None
        for months in window_candidates:
            res = get_stats(months)
            if not res:
                continue
            n, st = res
            if n >= int(min_n):
                chosen_months = months
                chosen_stats = st
                break
        if chosen_months is None or chosen_stats is None:
            return None

        # Deterministic method selection with fallback
        methods = [method] + [m for m in fallback_order if m != method]
        for m in methods:
            sig = self._volume_by_method(
                metric_id=metric_id,
                value=value,
                behavior=behavior,
                segment=segment,
                months=chosen_months,
                n=int(chosen_stats.get("n", 0)),
                stats=chosen_stats,
                method=m,
                params=method_params,
            )
            if sig is not None:
                return sig
        return None

    def _volume_by_method(
        self,
        *,
        metric_id: str,
        value: Decimal,
        behavior: VolumeBehavior,
        segment: str,
        months: int,
        n: int,
        stats: dict[str, Any],
        method: StatsMethod,
        params: dict[str, Any],
    ) -> StatsSignal | None:
        # Severity baseline based on behavior
        severe_threshold = Decimal("1.0")
        if behavior == VolumeBehavior.SPIKE_TOLERANT:
            severe_threshold = Decimal("2.0")
        elif behavior == VolumeBehavior.VOLATILE:
            severe_threshold = Decimal("1.5")

        if method == StatsMethod.PERCENTILE:
            p05 = _parse_decimal(stats.get("p05"))
            p95 = _parse_decimal(stats.get("p95"))
            if p05 is None or p95 is None:
                return None
            if value < p05:
                width = max(p95 - p05, Decimal(1))
                severity = "CRITICAL" if (p05 - value) / width >= severe_threshold else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="LOW_VOLUME",
                    metric_id=metric_id,
                    occurrence_id=None if segment in {"__ALL__", "__COLLISION__"} else segment,
                    is_triggered=True,
                    severity_suggested=severity,
                    score=None,
                    threshold_low=p05,
                    threshold_high=p95,
                    explanation_json={
                        "method": "PERCENTILE_BAND",
                        "window_months": months,
                        "segment": segment,
                        "n": n,
                        "value": str(value),
                        "p05": str(p05),
                        "p95": str(p95),
                    },
                )
            if value > p95:
                width = max(p95 - p05, Decimal(1))
                severity = "CRITICAL" if (value - p95) / width >= severe_threshold else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="HIGH_VOLUME",
                    metric_id=metric_id,
                    occurrence_id=None if segment in {"__ALL__", "__COLLISION__"} else segment,
                    is_triggered=True,
                    severity_suggested=severity,
                    score=None,
                    threshold_low=p05,
                    threshold_high=p95,
                    explanation_json={
                        "method": "PERCENTILE_BAND",
                        "window_months": months,
                        "segment": segment,
                        "n": n,
                        "value": str(value),
                        "p05": str(p05),
                        "p95": str(p95),
                    },
                )
            return None

        if method == StatsMethod.IQR:
            q1 = _parse_decimal(stats.get("q1"))
            q3 = _parse_decimal(stats.get("q3"))
            iqr = _parse_decimal(stats.get("iqr"))
            if q1 is None or q3 is None or iqr is None:
                return None
            k = Decimal(str(params.get("iqr_k", "1.5")))
            low = q1 - k * iqr
            high = q3 + k * iqr
            if value < low:
                severity = "CRITICAL" if (low - value) / max(iqr, Decimal(1)) >= severe_threshold else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="LOW_VOLUME",
                    metric_id=metric_id,
                    occurrence_id=None if segment in {"__ALL__", "__COLLISION__"} else segment,
                    is_triggered=True,
                    severity_suggested=severity,
                    score=None,
                    threshold_low=low,
                    threshold_high=high,
                    explanation_json={
                        "method": "IQR",
                        "iqr_k": str(k),
                        "window_months": months,
                        "segment": segment,
                        "n": n,
                        "value": str(value),
                        "q1": str(q1),
                        "q3": str(q3),
                        "iqr": str(iqr),
                        "low": str(low),
                        "high": str(high),
                    },
                )
            if value > high:
                severity = "CRITICAL" if (value - high) / max(iqr, Decimal(1)) >= severe_threshold else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="HIGH_VOLUME",
                    metric_id=metric_id,
                    occurrence_id=None if segment in {"__ALL__", "__COLLISION__"} else segment,
                    is_triggered=True,
                    severity_suggested=severity,
                    score=None,
                    threshold_low=low,
                    threshold_high=high,
                    explanation_json={
                        "method": "IQR",
                        "iqr_k": str(k),
                        "window_months": months,
                        "segment": segment,
                        "n": n,
                        "value": str(value),
                        "q1": str(q1),
                        "q3": str(q3),
                        "iqr": str(iqr),
                        "low": str(low),
                        "high": str(high),
                    },
                )
            return None

        if method == StatsMethod.Z_SCORE:
            mean = _parse_decimal(stats.get("mean"))
            std = _parse_decimal(stats.get("std"))
            if mean is None or std is None or std == 0:
                return None
            zthr = Decimal(str(params.get("z", "3.0")))
            z = (value - mean) / std
            low = mean - zthr * std
            high = mean + zthr * std
            if z < -zthr:
                severity = "CRITICAL" if abs(z) >= (zthr + Decimal("1.0")) else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="LOW_VOLUME",
                    metric_id=metric_id,
                    occurrence_id=None if segment in {"__ALL__", "__COLLISION__"} else segment,
                    is_triggered=True,
                    severity_suggested=severity,
                    score=abs(z),
                    threshold_low=low,
                    threshold_high=high,
                    explanation_json={
                        "method": "Z_SCORE",
                        "z_threshold": str(zthr),
                        "window_months": months,
                        "segment": segment,
                        "n": n,
                        "value": str(value),
                        "mean": str(mean),
                        "std": str(std),
                        "z": str(z),
                        "low": str(low),
                        "high": str(high),
                    },
                )
            if z > zthr:
                severity = "CRITICAL" if abs(z) >= (zthr + Decimal("1.0")) else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="HIGH_VOLUME",
                    metric_id=metric_id,
                    occurrence_id=None if segment in {"__ALL__", "__COLLISION__"} else segment,
                    is_triggered=True,
                    severity_suggested=severity,
                    score=abs(z),
                    threshold_low=low,
                    threshold_high=high,
                    explanation_json={
                        "method": "Z_SCORE",
                        "z_threshold": str(zthr),
                        "window_months": months,
                        "segment": segment,
                        "n": n,
                        "value": str(value),
                        "mean": str(mean),
                        "std": str(std),
                        "z": str(z),
                        "low": str(low),
                        "high": str(high),
                    },
                )
            return None

        # MEDIAN_BAND: use median +/- band_pct * median (default 0.5)
        if method == StatsMethod.MEDIAN_BAND:
            med = _parse_decimal(stats.get("median"))
            if med is None:
                return None
            band_pct = Decimal(str(params.get("band_pct", "0.5")))
            low = med * (Decimal(1) - band_pct)
            high = med * (Decimal(1) + band_pct)
            if value < low:
                severity = "CRITICAL" if (low - value) / max(med, Decimal(1)) >= severe_threshold else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="LOW_VOLUME",
                    metric_id=metric_id,
                    occurrence_id=None if segment in {"__ALL__", "__COLLISION__"} else segment,
                    is_triggered=True,
                    severity_suggested=severity,
                    score=None,
                    threshold_low=low,
                    threshold_high=high,
                    explanation_json={
                        "method": "MEDIAN_BAND",
                        "band_pct": str(band_pct),
                        "window_months": months,
                        "segment": segment,
                        "n": n,
                        "value": str(value),
                        "median": str(med),
                        "low": str(low),
                        "high": str(high),
                    },
                )
            if value > high:
                severity = "CRITICAL" if (value - high) / max(med, Decimal(1)) >= severe_threshold else "WARNING"
                return StatsSignal(
                    layer="STATS",
                    signal_type="HIGH_VOLUME",
                    metric_id=metric_id,
                    occurrence_id=None if segment in {"__ALL__", "__COLLISION__"} else segment,
                    is_triggered=True,
                    severity_suggested=severity,
                    score=None,
                    threshold_low=low,
                    threshold_high=high,
                    explanation_json={
                        "method": "MEDIAN_BAND",
                        "band_pct": str(band_pct),
                        "window_months": months,
                        "segment": segment,
                        "n": n,
                        "value": str(value),
                        "median": str(med),
                        "low": str(low),
                        "high": str(high),
                    },
                )
            return None

        return None


