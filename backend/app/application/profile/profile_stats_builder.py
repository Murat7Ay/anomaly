from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from dateutil.relativedelta import relativedelta

from app.application.calendar_service import CalendarService, CalendarWindow
from app.domain.profile.config import InstitutionProfileConfig
from app.domain.profile.schedule_resolver import ScheduleResolver
from app.infra.db.models.load import LoadBatch


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass(frozen=True)
class DailyAggregate:
    local_date: date

    debt_item_count: Decimal | None
    total_debt_amount: Decimal | None
    unique_customer_count: Decimal | None

    metrics: dict[str, Decimal]
    earliest_received_minutes: int | None

    def get_metric(self, metric_id: str) -> Decimal | None:
        if metric_id == "debt_item_count":
            return self.debt_item_count
        if metric_id == "total_debt_amount":
            return self.total_debt_amount
        if metric_id == "unique_customer_count":
            return self.unique_customer_count
        return self.metrics.get(metric_id)


def _to_decimal(v: Any) -> Decimal | None:
    if v is None:
        return None
    if isinstance(v, Decimal):
        return v
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, float):
        # Avoid binary float artifacts where possible
        return Decimal(str(v))
    if isinstance(v, str):
        try:
            return Decimal(v)
        except InvalidOperation:
            return None
    return None


def _median(sorted_vals: list[Decimal]) -> Decimal:
    n = len(sorted_vals)
    mid = n // 2
    if n % 2 == 1:
        return sorted_vals[mid]
    return (sorted_vals[mid - 1] + sorted_vals[mid]) / Decimal(2)


def _quantile_nearest_rank(sorted_vals: list[Decimal], p: Decimal) -> Decimal:
    """
    Nearest-rank quantile (deterministic, observed-value based).
    p in [0,1].
    """
    if not sorted_vals:
        raise ValueError("empty_values")
    if p <= 0:
        return sorted_vals[0]
    if p >= 1:
        return sorted_vals[-1]
    n = len(sorted_vals)
    # 1-indexed rank: ceil(p*n)
    rank = int((p * Decimal(n)).to_integral_value(rounding="ROUND_CEILING"))
    idx = max(rank - 1, 0)
    idx = min(idx, n - 1)
    return sorted_vals[idx]


def _stats(values: list[Decimal]) -> dict[str, Any]:
    if not values:
        return {
            "n": 0,
            "mean": None,
            "std": None,
            "median": None,
            "q1": None,
            "q3": None,
            "iqr": None,
            "p05": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    vals = sorted(values)
    n = len(vals)
    s = sum(vals)
    mean = s / Decimal(n)
    median = _median(vals)
    q1 = _quantile_nearest_rank(vals, Decimal("0.25"))
    q3 = _quantile_nearest_rank(vals, Decimal("0.75"))
    p05 = _quantile_nearest_rank(vals, Decimal("0.05"))
    p95 = _quantile_nearest_rank(vals, Decimal("0.95"))
    iqr = q3 - q1
    vmin = vals[0]
    vmax = vals[-1]

    std: Decimal | None
    if n <= 1:
        std = None
    else:
        # Sample stddev
        var = sum((x - mean) * (x - mean) for x in vals) / Decimal(n - 1)
        std = var.sqrt()

    def sdec(x: Decimal | None) -> str | None:
        if x is None:
            return None
        # Normalize for stable JSON (no exponent)
        return format(x.normalize(), "f")

    return {
        "n": n,
        "mean": sdec(mean),
        "std": sdec(std),
        "median": sdec(median),
        "q1": sdec(q1),
        "q3": sdec(q3),
        "iqr": sdec(iqr),
        "p05": sdec(p05),
        "p95": sdec(p95),
        "min": sdec(vmin),
        "max": sdec(vmax),
    }


class ProfileStatsBuilder:
    """
    Builds deterministic distribution snapshots (3/6/9/12 months) for volume + timing metrics.

    The snapshot is derived from historical LoadBatch data restricted to the profile's expected days.
    """

    ALGORITHM_VERSION = "stats_snapshot_v1"

    def __init__(self, *, calendar_service: CalendarService) -> None:
        self._cal = calendar_service
        self._resolver = ScheduleResolver(calendar_service)

    def build_snapshot(
        self,
        *,
        institution_id: uuid.UUID,
        profile: InstitutionProfileConfig,
        as_of_date: date,
        load_batches: list[LoadBatch],
    ) -> tuple[str, dict[str, Any], datetime]:
        """
        Returns: (snapshot_hash, snapshot_json, data_cutoff_utc)
        """
        # Cutoff: exclude current day to prevent leakage into thresholds used to evaluate that day.
        history_end_exclusive = as_of_date
        max_window_start = as_of_date - relativedelta(months=12)

        tz = ZoneInfo(profile.timezone)
        daily = self._aggregate_loads(load_batches=load_batches, tz=tz)

        # Build a calendar window that covers the full history range and shift padding.
        pad_days = 60
        window = self._cal.build_window_for_range(
            calendar_id=profile.calendar_id,
            start_date=max_window_start - timedelta(days=pad_days),
            end_date=as_of_date + timedelta(days=pad_days),
        )

        windows: dict[str, Any] = {}
        for months in (3, 6, 9, 12):
            start = as_of_date - relativedelta(months=months)
            if start < max_window_start:
                start = max_window_start
            end_inclusive = history_end_exclusive - timedelta(days=1)
            if end_inclusive < start:
                windows[str(months)] = {
                    "window_months": months,
                    "start_date": start.isoformat(),
                    "end_date_exclusive": history_end_exclusive.isoformat(),
                    "expected_dates_count": 0,
                    "observed_dates_count": 0,
                    "collision_dates_count": 0,
                    "metrics": {},
                    "timing": {},
                }
                continue

            expected_by_date = self._resolver.expected_by_date(
                schedule=profile.schedule, window=window, start_date=start, end_date=end_inclusive
            )
            collision_dates = {d for d, occs in expected_by_date.items() if len(occs) > 1}
            expected_dates = sorted(expected_by_date.keys())

            metrics_block: dict[str, Any] = {}
            for vm in profile.volume_models:
                segments: dict[str, list[Decimal]] = {}
                for d in expected_dates:
                    agg = daily.get(d)
                    if not agg:
                        continue
                    val = agg.get_metric(vm.metric_id)
                    if val is None:
                        continue
                    seg = "__ALL__"
                    if vm.segment_by_occurrence:
                        seg = (
                            expected_by_date[d][0].occurrence_id
                            if len(expected_by_date[d]) == 1
                            else "__COLLISION__"
                        )
                    segments.setdefault(seg, []).append(val)

                metrics_block[vm.metric_id] = {
                    "behavior": vm.behavior.value,
                    "method_policy": vm.method_policy.model_dump(mode="json"),
                    "segment_by_occurrence": vm.segment_by_occurrence,
                    "segments": {seg: _stats(vals) for seg, vals in segments.items()},
                }

            timing_segments: dict[str, list[Decimal]] = {}
            for d in expected_dates:
                agg = daily.get(d)
                if not agg or agg.earliest_received_minutes is None:
                    continue
                seg = "__ALL__"
                # Segment timing by occurrence only when unambiguous
                if len(expected_by_date[d]) == 1:
                    seg = expected_by_date[d][0].occurrence_id
                timing_segments.setdefault(seg, []).append(Decimal(agg.earliest_received_minutes))

            windows[str(months)] = {
                "window_months": months,
                "start_date": start.isoformat(),
                "end_date_exclusive": history_end_exclusive.isoformat(),
                "expected_dates_count": len(expected_dates),
                "observed_dates_count": sum(1 for d in expected_dates if d in daily),
                "collision_dates_count": len(collision_dates),
                "metrics": metrics_block,
                "timing": {"segments": {seg: _stats(vals) for seg, vals in timing_segments.items()}},
            }

        snapshot_json: dict[str, Any] = {
            "schema_version": 1,
            "algorithm_version": self.ALGORITHM_VERSION,
            "institution_id": str(institution_id),
            "as_of_date": as_of_date.isoformat(),
            "timezone": profile.timezone,
            "calendar_id": str(profile.calendar_id),
            "cutoff_local_date_exclusive": history_end_exclusive.isoformat(),
            "windows": windows,
        }

        snapshot_hash = hashlib.sha256(
            json.dumps(snapshot_json, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        # Audit-only timestamp (not part of snapshot hash): when the snapshot was computed.
        return snapshot_hash, snapshot_json, utc_now()

    def _aggregate_loads(self, *, load_batches: list[LoadBatch], tz: ZoneInfo) -> dict[date, DailyAggregate]:
        """
        Aggregation policy (deterministic defaults):
        - debt_item_count: sum
        - total_debt_amount: sum
        - unique_customer_count: max (avoids double-counting across multiple batches)
        - metrics_json numeric keys: sum per key
        - earliest_received_minutes: min(received_at_local minutes-from-midnight)
        """
        acc: dict[date, dict[str, Any]] = {}
        for lb in load_batches:
            d = lb.institution_local_date
            bucket = acc.setdefault(
                d,
                {
                    "debt_item_count": Decimal(0),
                    "debt_item_count_any": False,
                    "total_debt_amount": Decimal(0),
                    "total_debt_amount_any": False,
                    "unique_customer_count": None,
                    "metrics": {},
                    "earliest_minutes": None,
                },
            )

            if lb.debt_item_count is not None:
                bucket["debt_item_count"] += Decimal(int(lb.debt_item_count))
                bucket["debt_item_count_any"] = True

            if lb.total_debt_amount is not None:
                bucket["total_debt_amount"] += _to_decimal(lb.total_debt_amount) or Decimal(0)
                bucket["total_debt_amount_any"] = True

            if lb.unique_customer_count is not None:
                v = Decimal(int(lb.unique_customer_count))
                cur = bucket["unique_customer_count"]
                bucket["unique_customer_count"] = v if cur is None else max(cur, v)

            # metrics_json: sum numeric
            if isinstance(lb.metrics_json, dict):
                for k, raw_v in lb.metrics_json.items():
                    dv = _to_decimal(raw_v)
                    if dv is None:
                        continue
                    bucket["metrics"][k] = bucket["metrics"].get(k, Decimal(0)) + dv

            # timing
            if lb.received_at_utc is not None:
                local_dt = lb.received_at_utc.astimezone(tz)
                minutes = local_dt.hour * 60 + local_dt.minute
                cur_min = bucket["earliest_minutes"]
                bucket["earliest_minutes"] = minutes if cur_min is None else min(cur_min, minutes)

        out: dict[date, DailyAggregate] = {}
        for d, b in acc.items():
            out[d] = DailyAggregate(
                local_date=d,
                debt_item_count=b["debt_item_count"] if b["debt_item_count_any"] else None,
                total_debt_amount=b["total_debt_amount"] if b["total_debt_amount_any"] else None,
                unique_customer_count=b["unique_customer_count"],
                metrics=b["metrics"],
                earliest_received_minutes=b["earliest_minutes"],
            )
        return out


