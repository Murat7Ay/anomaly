from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.profile.config import ScheduleSpec


class DslRuleType(str, Enum):
    EXPECT_LOAD_BY_RUN = "EXPECT_LOAD_BY_RUN"
    UNEXPECTED_LOAD_DAY = "UNEXPECTED_LOAD_DAY"
    ABSOLUTE_VOLUME_BOUNDS = "ABSOLUTE_VOLUME_BOUNDS"
    ARRIVAL_TIME_BOUNDS = "ARRIVAL_TIME_BOUNDS"


class AllowedAnomalyType(str, Enum):
    NO_DATA = "NO_DATA"
    UNEXPECTED_DAY = "UNEXPECTED_DAY"
    HIGH_VOLUME = "HIGH_VOLUME"
    LOW_VOLUME = "LOW_VOLUME"
    EARLY_LOAD = "EARLY_LOAD"
    LATE_LOAD = "LATE_LOAD"


class ScheduleSource(str, Enum):
    PROFILE = "PROFILE"
    CUSTOM = "CUSTOM"


class RunSelector(str, Enum):
    CURRENT = "CURRENT"
    AM_0900 = "AM_0900"
    PM_1400 = "PM_1400"


class DslScheduleRef(BaseModel):
    source: ScheduleSource = ScheduleSource.PROFILE
    custom_schedule: ScheduleSpec | None = None

    @model_validator(mode="after")
    def _validate_custom(self) -> "DslScheduleRef":
        if self.source == ScheduleSource.CUSTOM and self.custom_schedule is None:
            raise ValueError("custom_schedule_required")
        if self.source == ScheduleSource.PROFILE and self.custom_schedule is not None:
            raise ValueError("custom_schedule_not_allowed_for_profile_source")
        return self


class DslRuleBase(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    enabled: bool = True
    description: str | None = Field(default=None, max_length=512)
    anomaly_type: AllowedAnomalyType
    message: str = Field(min_length=1, max_length=512)


class ExpectLoadByRunParams(BaseModel):
    schedule: DslScheduleRef = Field(default_factory=DslScheduleRef)
    run: RunSelector = RunSelector.CURRENT
    include_collisions: bool = True


class UnexpectedLoadDayParams(BaseModel):
    schedule: DslScheduleRef = Field(default_factory=DslScheduleRef)


class AbsoluteVolumeBoundsParams(BaseModel):
    schedule: DslScheduleRef = Field(default_factory=DslScheduleRef)
    run: RunSelector = RunSelector.CURRENT
    apply_only_on_expected_days: bool = True

    metric_id: str = Field(min_length=1, max_length=64)
    min_inclusive: str | None = None  # Decimal as string
    max_inclusive: str | None = None  # Decimal as string

    @model_validator(mode="after")
    def _validate_bounds(self) -> "AbsoluteVolumeBoundsParams":
        if self.min_inclusive is None and self.max_inclusive is None:
            raise ValueError("min_or_max_required")
        dmin = Decimal(self.min_inclusive) if self.min_inclusive is not None else None
        dmax = Decimal(self.max_inclusive) if self.max_inclusive is not None else None
        if dmin is not None and dmax is not None and dmin > dmax:
            raise ValueError("min_greater_than_max")
        return self


class ArrivalTimeBoundsParams(BaseModel):
    schedule: DslScheduleRef = Field(default_factory=DslScheduleRef)
    run: RunSelector = RunSelector.CURRENT
    apply_only_on_expected_days: bool = True

    earliest_minutes_inclusive: int | None = Field(default=None, ge=0, le=1439)
    latest_minutes_inclusive: int | None = Field(default=None, ge=0, le=1439)

    @model_validator(mode="after")
    def _validate_bounds(self) -> "ArrivalTimeBoundsParams":
        if self.earliest_minutes_inclusive is None and self.latest_minutes_inclusive is None:
            raise ValueError("earliest_or_latest_required")
        if (
            self.earliest_minutes_inclusive is not None
            and self.latest_minutes_inclusive is not None
            and self.earliest_minutes_inclusive > self.latest_minutes_inclusive
        ):
            raise ValueError("earliest_greater_than_latest")
        return self


class DslRuleExpectLoadByRun(DslRuleBase):
    type: Literal[DslRuleType.EXPECT_LOAD_BY_RUN]
    params: ExpectLoadByRunParams

    @model_validator(mode="after")
    def _validate_anomaly_type(self) -> "DslRuleExpectLoadByRun":
        if self.anomaly_type not in {AllowedAnomalyType.NO_DATA, AllowedAnomalyType.LATE_LOAD}:
            raise ValueError("invalid_anomaly_type_for_rule")
        return self


class DslRuleUnexpectedLoadDay(DslRuleBase):
    type: Literal[DslRuleType.UNEXPECTED_LOAD_DAY]
    params: UnexpectedLoadDayParams

    @model_validator(mode="after")
    def _validate_anomaly_type(self) -> "DslRuleUnexpectedLoadDay":
        if self.anomaly_type != AllowedAnomalyType.UNEXPECTED_DAY:
            raise ValueError("invalid_anomaly_type_for_rule")
        return self


class DslRuleAbsoluteVolumeBounds(DslRuleBase):
    type: Literal[DslRuleType.ABSOLUTE_VOLUME_BOUNDS]
    params: AbsoluteVolumeBoundsParams

    @model_validator(mode="after")
    def _validate_anomaly_type(self) -> "DslRuleAbsoluteVolumeBounds":
        if self.anomaly_type not in {AllowedAnomalyType.HIGH_VOLUME, AllowedAnomalyType.LOW_VOLUME}:
            raise ValueError("invalid_anomaly_type_for_rule")
        if self.anomaly_type == AllowedAnomalyType.LOW_VOLUME:
            if self.params.min_inclusive is None or self.params.max_inclusive is not None:
                raise ValueError("low_volume_requires_only_min")
        if self.anomaly_type == AllowedAnomalyType.HIGH_VOLUME:
            if self.params.max_inclusive is None or self.params.min_inclusive is not None:
                raise ValueError("high_volume_requires_only_max")
        return self


class DslRuleArrivalTimeBounds(DslRuleBase):
    type: Literal[DslRuleType.ARRIVAL_TIME_BOUNDS]
    params: ArrivalTimeBoundsParams

    @model_validator(mode="after")
    def _validate_anomaly_type(self) -> "DslRuleArrivalTimeBounds":
        if self.anomaly_type not in {AllowedAnomalyType.EARLY_LOAD, AllowedAnomalyType.LATE_LOAD}:
            raise ValueError("invalid_anomaly_type_for_rule")
        if self.anomaly_type == AllowedAnomalyType.EARLY_LOAD:
            if self.params.earliest_minutes_inclusive is None or self.params.latest_minutes_inclusive is not None:
                raise ValueError("early_load_requires_only_earliest")
        if self.anomaly_type == AllowedAnomalyType.LATE_LOAD:
            if self.params.latest_minutes_inclusive is None or self.params.earliest_minutes_inclusive is not None:
                raise ValueError("late_load_requires_only_latest")
        return self


DslRule = Annotated[
    DslRuleExpectLoadByRun
    | DslRuleUnexpectedLoadDay
    | DslRuleAbsoluteVolumeBounds
    | DslRuleArrivalTimeBounds,
    Field(discriminator="type"),
]


class DslRuleSet(BaseModel):
    schema_version: int = Field(default=1, ge=1, le=10)
    rules: list[DslRule] = Field(min_length=1)

    @field_validator("rules")
    @classmethod
    def _unique_rule_ids(cls, v: list[DslRule]) -> list[DslRule]:
        ids = [r.id for r in v]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate_rule_id")
        return v

    def canonical_json(self) -> dict[str, Any]:
        # Deterministic: sort rules by id
        data = self.model_dump(mode="json")
        data["rules"] = sorted(data["rules"], key=lambda r: r["id"])
        return data

    def compiled_hash(self) -> str:
        raw = json.dumps(self.canonical_json(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


