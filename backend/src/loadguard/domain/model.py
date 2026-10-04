"""Value objects shared by the detection engine. No I/O, no ORM."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from loadguard.domain.calendar import MonthPhase
from loadguard.domain.contract import Severity


@dataclass(frozen=True)
class LoadFacts:
    """Summary of one delivered debt file, computed by the ingestion edge (parser/SFTP watcher)."""

    id: str
    received_at: datetime  # UTC aware
    content_hash: str
    record_count: int
    total_amount: float
    customer_count: int
    zero_amount_count: int = 0
    negative_amount_count: int = 0
    duplicate_record_count: int = 0
    max_amount: float | None = None


def aggregate_metrics(loads: list[LoadFacts]) -> dict[str, float]:
    """Slot-level metrics. Multiple files for one slot are treated as partitions of one delivery."""
    if not loads:
        return {}
    records = sum(lf.record_count for lf in loads)
    amount = sum(lf.total_amount for lf in loads)
    customers = sum(lf.customer_count for lf in loads)
    zeros = sum(lf.zero_amount_count for lf in loads)
    negatives = sum(lf.negative_amount_count for lf in loads)
    dups = sum(lf.duplicate_record_count for lf in loads)
    max_amounts = [lf.max_amount for lf in loads if lf.max_amount is not None]
    out = {
        "record_count": float(records),
        "total_amount": float(amount),
        "customer_count": float(customers),
        "avg_amount": amount / records if records else 0.0,
        "zero_amount_ratio": zeros / records if records else 0.0,
        "negative_amount_count": float(negatives),
        "duplicate_record_ratio": dups / records if records else 0.0,
        "file_count": float(len(loads)),
    }
    if max_amounts:
        out["max_amount"] = max(max_amounts)
    return out


class OccurrenceStatus(StrEnum):
    PENDING = "PENDING"  # expected, window still open
    AT_RISK = "AT_RISK"  # not yet received and later than it usually is
    RECEIVED = "RECEIVED"  # received on time
    LATE = "LATE"  # received after deadline
    MISSING = "MISSING"  # deadline passed, nothing received
    UNSCHEDULED = "UNSCHEDULED"  # delivery nobody expected


@dataclass(frozen=True)
class HistoryPoint:
    """A past occurrence of the same slot, used to learn the institution's normal."""

    business_date: date
    weekday: int
    month_phase: MonthPhase
    metrics: dict[str, float]
    first_arrival_minutes: int | None  # local minutes after midnight
    excluded: bool = False  # confirmed anomaly / known event: never learn from it
    regime_break: bool = False  # analyst confirmed a permanent "new normal" starting here


class Category(StrEnum):
    TIMELINESS = "TIMELINESS"
    VOLUME = "VOLUME"
    QUALITY = "QUALITY"
    RULE = "RULE"


@dataclass(frozen=True)
class Finding:
    code: str
    category: Category
    severity: Severity
    message: str
    metric: str | None = None
    observed: float | None = None
    expected: float | None = None
    lower: float | None = None
    upper: float | None = None
    score: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "metric": self.metric,
            "observed": self.observed,
            "expected": self.expected,
            "lower": self.lower,
            "upper": self.upper,
            "score": self.score,
            "evidence": self.evidence,
        }
