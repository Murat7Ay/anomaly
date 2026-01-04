from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.enums import ShiftRule


class Cadence(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"
    SPECIFIC_DATES = "SPECIFIC_DATES"


class DailyKind(str, Enum):
    ALL_DAYS = "ALL_DAYS"
    BUSINESS_DAYS = "BUSINESS_DAYS"


class VolumeBehavior(str, Enum):
    STABLE = "STABLE"
    VOLATILE = "VOLATILE"
    SPIKE_TOLERANT = "SPIKE_TOLERANT"


class StatsMethod(str, Enum):
    PERCENTILE = "PERCENTILE"
    IQR = "IQR"
    Z_SCORE = "Z_SCORE"
    MEDIAN_BAND = "MEDIAN_BAND"


ExpectedByRun = Literal["AM_0900", "PM_1400"]


class MaturityPolicy(BaseModel):
    first_seen_date: date
    stats_enabled_after_days: int = Field(default=180, ge=0, le=3650)
    ml_enabled_after_days: int = Field(default=180, ge=0, le=3650)
    min_expected_loads_for_stats: int = Field(default=12, ge=0, le=10_000)
    min_expected_loads_for_ml: int = Field(default=24, ge=0, le=10_000)


class MethodPolicy(BaseModel):
    primary_method: StatsMethod
    params: dict = Field(default_factory=dict)
    fallback_order: list[StatsMethod] = Field(default_factory=list)
    window_months: Literal[3, 6, 9, 12] = 6
    min_n: int = Field(default=12, ge=0, le=10_000)


class VolumeModel(BaseModel):
    metric_id: str = Field(min_length=1, max_length=64)
    behavior: VolumeBehavior = VolumeBehavior.STABLE
    method_policy: MethodPolicy
    segment_by_occurrence: bool = True


class OccurrenceSpec(BaseModel):
    occurrence_id: str = Field(min_length=1, max_length=64)
    cadence: Cadence
    shift_rule: ShiftRule = ShiftRule.NEXT_BUSINESS_DAY
    expected_by_run: ExpectedByRun = "PM_1400"
    grace_minutes: int = Field(default=0, ge=0, le=24 * 60)
    max_late_business_days: int = Field(default=0, ge=0, le=31)

    # DAILY
    daily_kind: DailyKind | None = None

    # WEEKLY
    days_of_week_iso: list[int] | None = None  # ISO weekday: Mon=1..Sun=7

    # BIWEEKLY
    biweekly_anchor_date: date | None = None
    biweekly_weekday_iso: int | None = Field(default=None, ge=1, le=7)

    # MONTHLY
    days_of_month: list[int] | None = None  # 1..31
    last_business_day: bool = False

    # SPECIFIC_DATES (recurring by MM-DD)
    month_day_patterns: list[str] | None = None  # ["01-15", "12-31"]

    @field_validator("days_of_week_iso")
    @classmethod
    def _validate_days_of_week(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("days_of_week_iso_empty")
        for d in v:
            if d < 1 or d > 7:
                raise ValueError("days_of_week_iso_out_of_range")
        return sorted(set(v))

    @field_validator("days_of_month")
    @classmethod
    def _validate_days_of_month(cls, v: list[int] | None) -> list[int] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("days_of_month_empty")
        for d in v:
            if d < 1 or d > 31:
                raise ValueError("days_of_month_out_of_range")
        return sorted(set(v))

    @field_validator("month_day_patterns")
    @classmethod
    def _validate_month_day_patterns(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        if not v:
            raise ValueError("month_day_patterns_empty")
        pat = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])$")
        out: set[str] = set()
        for s in v:
            if not pat.match(s):
                raise ValueError("month_day_pattern_invalid")
            out.add(s)
        return sorted(out)

    @model_validator(mode="after")
    def _validate_by_cadence(self) -> "OccurrenceSpec":
        if self.cadence == Cadence.DAILY:
            if self.daily_kind is None:
                raise ValueError("daily_kind_required")
        elif self.cadence == Cadence.WEEKLY:
            if not self.days_of_week_iso:
                raise ValueError("days_of_week_iso_required")
        elif self.cadence == Cadence.BIWEEKLY:
            if self.biweekly_anchor_date is None or self.biweekly_weekday_iso is None:
                raise ValueError("biweekly_anchor_date_and_weekday_required")
            if self.biweekly_anchor_date.isoweekday() != self.biweekly_weekday_iso:
                raise ValueError("biweekly_anchor_weekday_mismatch")
        elif self.cadence == Cadence.MONTHLY:
            if not (self.days_of_month or self.last_business_day):
                raise ValueError("monthly_anchor_required")
        elif self.cadence == Cadence.SPECIFIC_DATES:
            if not self.month_day_patterns:
                raise ValueError("month_day_patterns_required")
        else:
            raise ValueError("unsupported_cadence")
        return self


class ScheduleSpec(BaseModel):
    occurrences: list[OccurrenceSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_unique_occurrence_ids(self) -> "ScheduleSpec":
        ids = [o.occurrence_id for o in self.occurrences]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_occurrence_id")
        return self


class InstitutionProfileConfig(BaseModel):
    timezone: str = Field(min_length=1, max_length=64)
    calendar_id: uuid.UUID
    maturity_policy: MaturityPolicy
    schedule: ScheduleSpec
    volume_models: list[VolumeModel] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_unique_metric_ids(self) -> "InstitutionProfileConfig":
        ids = [m.metric_id for m in self.volume_models]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_metric_id")
        return self

    def canonical_json(self) -> dict:
        # Pydantic v2: mode="json" converts dates/uuids to JSON-friendly forms deterministically.
        return self.model_dump(mode="json")

    def config_hash(self) -> str:
        raw = json.dumps(self.canonical_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


