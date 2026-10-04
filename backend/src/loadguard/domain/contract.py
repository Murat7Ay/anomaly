"""Delivery contract: what an institution (biller) promised to send, when, and how we watch it.

A contract is versioned, approved under four-eyes, and hashed. Every evaluation records the hash
of the contract it ran under so any decision can be reproduced later.
"""

from __future__ import annotations

import hashlib
import json
from datetime import time
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

UNSCHEDULED_SLOT = "__unscheduled__"


class Cadence(StrEnum):
    BUSINESS_DAYS = "BUSINESS_DAYS"  # every business day (holidays/weekends simply not expected)
    EVERY_DAY = "EVERY_DAY"  # 7/24 billers (telecom, some utilities)
    WEEKLY = "WEEKLY"
    MONTHLY = "MONTHLY"


class HolidayShift(StrEnum):
    NEXT_BUSINESS_DAY = "NEXT_BUSINESS_DAY"
    PREVIOUS_BUSINESS_DAY = "PREVIOUS_BUSINESS_DAY"
    SKIP = "SKIP"
    NONE = "NONE"  # still expected on the holiday itself


class Sensitivity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Direction(StrEnum):
    BOTH = "BOTH"
    LOW_ONLY = "LOW_ONLY"
    HIGH_ONLY = "HIGH_ONLY"


class Severity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return {"INFO": 1, "WARNING": 2, "CRITICAL": 3}[self.value]


class WatchedMetric(StrEnum):
    RECORD_COUNT = "record_count"
    TOTAL_AMOUNT = "total_amount"
    CUSTOMER_COUNT = "customer_count"
    AVG_AMOUNT = "avg_amount"


class LimitMetric(StrEnum):
    RECORD_COUNT = "record_count"
    TOTAL_AMOUNT = "total_amount"
    CUSTOMER_COUNT = "customer_count"
    AVG_AMOUNT = "avg_amount"
    ZERO_AMOUNT_RATIO = "zero_amount_ratio"
    NEGATIVE_AMOUNT_COUNT = "negative_amount_count"
    DUPLICATE_RECORD_RATIO = "duplicate_record_ratio"
    MAX_AMOUNT = "max_amount"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DeliverySlot(_Strict):
    """One recurring delivery the institution owes us."""

    key: str = Field(min_length=1, max_length=48, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    label: str = Field(min_length=1, max_length=120)
    cadence: Cadence
    weekdays: list[int] | None = Field(default=None, description="ISO weekdays (1=Mon) for WEEKLY")
    month_days: list[int] | None = Field(default=None, description="Days of month (1-31) for MONTHLY")
    last_business_day: bool = False
    holiday_shift: HolidayShift = HolidayShift.NEXT_BUSINESS_DAY
    window_start: time = Field(description="Earliest normal arrival (local time)")
    deadline: time = Field(description="After this (plus grace) a missing file is an incident")
    grace_minutes: int = Field(default=0, ge=0, le=240)

    @field_validator("weekdays")
    @classmethod
    def _weekdays(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        if not v or any(d < 1 or d > 7 for d in v):
            raise ValueError("weekdays must be non-empty ISO weekdays 1..7")
        return sorted(set(v))

    @field_validator("month_days")
    @classmethod
    def _month_days(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        if not v or any(d < 1 or d > 31 for d in v):
            raise ValueError("month_days must be non-empty days 1..31")
        return sorted(set(v))

    @model_validator(mode="after")
    def _by_cadence(self) -> DeliverySlot:
        if self.cadence == Cadence.WEEKLY and not self.weekdays:
            raise ValueError("WEEKLY cadence requires weekdays")
        if self.cadence == Cadence.MONTHLY and not (self.month_days or self.last_business_day):
            raise ValueError("MONTHLY cadence requires month_days or last_business_day")
        if self.cadence in (Cadence.BUSINESS_DAYS, Cadence.EVERY_DAY) and (self.weekdays or self.month_days):
            raise ValueError(f"{self.cadence} cadence does not take weekdays/month_days")
        if self.deadline <= self.window_start:
            raise ValueError("deadline must be after window_start (same local day)")
        return self


class MetricWatch(_Strict):
    metric: WatchedMetric
    sensitivity: Sensitivity = Sensitivity.MEDIUM
    direction: Direction = Direction.BOTH


class HardLimit(_Strict):
    """Deterministic business rule. Always applied, independent of learned baselines."""

    id: str = Field(min_length=1, max_length=48, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    metric: LimitMetric
    min: float | None = None
    max: float | None = None
    severity: Literal[Severity.WARNING, Severity.CRITICAL] = Severity.CRITICAL
    note: str | None = Field(default=None, max_length=240)

    @model_validator(mode="after")
    def _bounds(self) -> HardLimit:
        if self.min is None and self.max is None:
            raise ValueError("limit needs min or max")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class QualityPolicy(_Strict):
    detect_duplicate_file: bool = True
    detect_stale_data: bool = True
    detect_unit_scale: bool = True
    max_zero_amount_ratio: float = Field(default=0.05, ge=0, le=1)
    max_duplicate_record_ratio: float = Field(default=0.01, ge=0, le=1)
    forbid_negative_amounts: bool = True
    unexpected_delivery: Literal["IGNORE", "INFO", "WARNING"] = "INFO"


class LearningPolicy(_Strict):
    lookback_days: int = Field(default=180, ge=30, le=730)
    min_history: int = Field(default=8, ge=4, le=200)


class ContractSpec(_Strict):
    schema_version: Literal[1] = 1
    timezone: str = "Europe/Istanbul"
    calendar: str = "TR"
    slots: list[DeliverySlot] = Field(min_length=1)
    metrics: list[MetricWatch] = Field(default_factory=list)
    limits: list[HardLimit] = Field(default_factory=list)
    quality: QualityPolicy = Field(default_factory=QualityPolicy)
    learning: LearningPolicy = Field(default_factory=LearningPolicy)

    @model_validator(mode="after")
    def _unique(self) -> ContractSpec:
        keys = [s.key for s in self.slots]
        if len(keys) != len(set(keys)):
            raise ValueError("slot keys must be unique")
        if UNSCHEDULED_SLOT in keys:
            raise ValueError("reserved slot key")
        ms = [m.metric for m in self.metrics]
        if len(ms) != len(set(ms)):
            raise ValueError("each metric may be watched once")
        ids = [lim.id for lim in self.limits]
        if len(ids) != len(set(ids)):
            raise ValueError("limit ids must be unique")
        return self

    def slot(self, key: str) -> DeliverySlot | None:
        return next((s for s in self.slots if s.key == key), None)

    def canonical(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def spec_hash(self) -> str:
        raw = json.dumps(self.canonical(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()
