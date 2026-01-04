from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Mapping

from app.application.calendar_service import CalendarService, CalendarWindow
from app.domain.dsl.schema import (
    AllowedAnomalyType,
    DslRule,
    DslRuleAbsoluteVolumeBounds,
    DslRuleArrivalTimeBounds,
    DslRuleExpectLoadByRun,
    DslRuleSet,
    DslRuleType,
    DslRuleUnexpectedLoadDay,
    RunSelector,
    ScheduleSource,
)
from app.domain.profile.config import InstitutionProfileConfig, ScheduleSpec
from app.domain.profile.schedule_resolver import ScheduleResolver


def _run_to_minutes(run_type: str, *, am_minutes: int, pm_minutes: int) -> int:
    if run_type == "AM_0900":
        return am_minutes
    if run_type == "PM_1400":
        return pm_minutes
    raise ValueError(f"unsupported_run_type:{run_type}")


def _selector_to_run(selector: RunSelector, current_run: str) -> str:
    if selector == RunSelector.CURRENT:
        return current_run
    return selector.value


@dataclass(frozen=True)
class DslEvaluationContext:
    institution_id: uuid.UUID
    as_of_date: date
    run_type: str  # AM_0900 | PM_1400

    # Aggregated daily state (already normalized to institution local date/time)
    has_load: bool
    load_count: int
    earliest_received_minutes: int | None
    metrics: Mapping[str, Decimal]


@dataclass(frozen=True)
class DslRuleHit:
    rule_id: str
    anomaly_type: str
    message: str
    evidence: dict[str, Any]


@dataclass(frozen=True)
class DslEvaluationResult:
    triggered: bool
    hits: list[DslRuleHit]


class DslEngine:
    """
    Deterministic DSL evaluator.

    Semantics:
    - Rules are OR'ed: any matching rule yields a DSL anomaly.
    - DSL anomalies are always treated as CRITICAL by the final aggregator (outside this engine).
    """

    def __init__(self, *, calendar_service: CalendarService, am_run_minutes: int = 9 * 60, pm_run_minutes: int = 14 * 60) -> None:
        self._cal = calendar_service
        self._am = am_run_minutes
        self._pm = pm_run_minutes
        self._resolver = ScheduleResolver(calendar_service)

    def evaluate(
        self,
        *,
        rule_set: DslRuleSet,
        profile: InstitutionProfileConfig,
        ctx: DslEvaluationContext,
    ) -> DslEvaluationResult:
        window = self._cal.build_window_for_range(
            calendar_id=profile.calendar_id,
            start_date=ctx.as_of_date - timedelta(days=60),
            end_date=ctx.as_of_date + timedelta(days=60),
        )

        hits: list[DslRuleHit] = []
        for rule in sorted(rule_set.rules, key=lambda r: r.id):
            if not rule.enabled:
                continue
            hit = self._eval_rule(rule=rule, profile=profile, window=window, ctx=ctx)
            if hit:
                hits.append(hit)
        return DslEvaluationResult(triggered=bool(hits), hits=hits)

    def _schedule_for_rule(self, *, rule: DslRule, profile: InstitutionProfileConfig) -> ScheduleSpec:
        ref = getattr(rule, "params").schedule  # all current rules have schedule ref
        if ref.source == ScheduleSource.PROFILE:
            return profile.schedule
        assert ref.custom_schedule is not None
        return ref.custom_schedule

    def _expected_occurrences_today(
        self,
        *,
        schedule: ScheduleSpec,
        window: CalendarWindow,
        as_of_date: date,
    ):
        return self._resolver.expected_occurrences_for_range(
            schedule=schedule, window=window, start_date=as_of_date, end_date=as_of_date
        )

    def _expected_for_run(
        self,
        *,
        schedule: ScheduleSpec,
        window: CalendarWindow,
        as_of_date: date,
        selected_run: str,
        include_collisions: bool,
    ) -> tuple[bool, dict[str, Any]]:
        occs = self._expected_occurrences_today(schedule=schedule, window=window, as_of_date=as_of_date)
        occs_for_run = [o for o in occs if o.expected_by_run == selected_run]
        if not occs_for_run:
            return False, {"expected_occurrences": []}

        if (not include_collisions) and len(occs_for_run) > 1:
            return False, {"expected_occurrences": [o.__dict__ for o in occs_for_run], "collision_skipped": True}

        return True, {"expected_occurrences": [o.__dict__ for o in occs_for_run]}

    def _eval_rule(
        self,
        *,
        rule: DslRule,
        profile: InstitutionProfileConfig,
        window: CalendarWindow,
        ctx: DslEvaluationContext,
    ) -> DslRuleHit | None:
        schedule = self._schedule_for_rule(rule=rule, profile=profile)

        if rule.type == DslRuleType.UNEXPECTED_LOAD_DAY:
            assert isinstance(rule, DslRuleUnexpectedLoadDay)
            if not ctx.has_load:
                return None
            occs = self._expected_occurrences_today(schedule=schedule, window=window, as_of_date=ctx.as_of_date)
            if occs:
                return None
            return DslRuleHit(
                rule_id=rule.id,
                anomaly_type=rule.anomaly_type.value,
                message=rule.message,
                evidence={"has_load": ctx.has_load, "load_count": ctx.load_count, "expected_occurrences": []},
            )

        if rule.type == DslRuleType.EXPECT_LOAD_BY_RUN:
            assert isinstance(rule, DslRuleExpectLoadByRun)
            selected_run = _selector_to_run(rule.params.run, ctx.run_type)
            expected, evidence = self._expected_for_run(
                schedule=schedule,
                window=window,
                as_of_date=ctx.as_of_date,
                selected_run=selected_run,
                include_collisions=rule.params.include_collisions,
            )
            if not expected:
                return None

            run_minutes = _run_to_minutes(selected_run, am_minutes=self._am, pm_minutes=self._pm)
            # Use max grace among occurrences for this run to reduce false positives
            grace = 0
            for o in evidence.get("expected_occurrences", []):
                grace = max(grace, int(o.get("grace_minutes", 0)))
            cutoff = run_minutes + grace

            received = ctx.earliest_received_minutes
            has_by_cutoff = received is not None and received <= cutoff

            if has_by_cutoff:
                return None

            if rule.anomaly_type == AllowedAnomalyType.NO_DATA:
                if ctx.has_load:
                    # Data exists but not by cutoff -> classify as late, not no-data.
                    return None
            if rule.anomaly_type == AllowedAnomalyType.LATE_LOAD:
                if not ctx.has_load:
                    # Can't classify late without a received time
                    return None
                if received is None or received <= cutoff:
                    return None

            evidence.update(
                {
                    "selected_run": selected_run,
                    "run_minutes": run_minutes,
                    "grace_minutes_used": grace,
                    "cutoff_minutes": cutoff,
                    "earliest_received_minutes": received,
                    "has_load": ctx.has_load,
                    "load_count": ctx.load_count,
                }
            )
            return DslRuleHit(rule_id=rule.id, anomaly_type=rule.anomaly_type.value, message=rule.message, evidence=evidence)

        if rule.type == DslRuleType.ABSOLUTE_VOLUME_BOUNDS:
            assert isinstance(rule, DslRuleAbsoluteVolumeBounds)
            selected_run = _selector_to_run(rule.params.run, ctx.run_type)
            expected, evidence = (True, {"expected_occurrences": []})
            if rule.params.apply_only_on_expected_days:
                expected, evidence = self._expected_for_run(
                    schedule=schedule,
                    window=window,
                    as_of_date=ctx.as_of_date,
                    selected_run=selected_run,
                    include_collisions=True,
                )
            if not expected:
                return None

            v = ctx.metrics.get(rule.params.metric_id)
            if v is None:
                return None

            dmin = Decimal(rule.params.min_inclusive) if rule.params.min_inclusive is not None else None
            dmax = Decimal(rule.params.max_inclusive) if rule.params.max_inclusive is not None else None
            if rule.anomaly_type == AllowedAnomalyType.LOW_VOLUME:
                if dmin is None or v >= dmin:
                    return None
                evidence.update({"metric_id": rule.params.metric_id, "value": str(v), "min_inclusive": str(dmin)})
            else:
                if dmax is None or v <= dmax:
                    return None
                evidence.update({"metric_id": rule.params.metric_id, "value": str(v), "max_inclusive": str(dmax)})

            evidence.update({"selected_run": selected_run})
            return DslRuleHit(rule_id=rule.id, anomaly_type=rule.anomaly_type.value, message=rule.message, evidence=evidence)

        if rule.type == DslRuleType.ARRIVAL_TIME_BOUNDS:
            assert isinstance(rule, DslRuleArrivalTimeBounds)
            selected_run = _selector_to_run(rule.params.run, ctx.run_type)
            expected, evidence = (True, {"expected_occurrences": []})
            if rule.params.apply_only_on_expected_days:
                expected, evidence = self._expected_for_run(
                    schedule=schedule,
                    window=window,
                    as_of_date=ctx.as_of_date,
                    selected_run=selected_run,
                    include_collisions=True,
                )
            if not expected:
                return None

            received = ctx.earliest_received_minutes
            if received is None:
                return None

            if rule.anomaly_type == AllowedAnomalyType.EARLY_LOAD:
                earliest = rule.params.earliest_minutes_inclusive
                if earliest is None or received >= earliest:
                    return None
                evidence.update({"earliest_minutes_inclusive": earliest})
            else:
                latest = rule.params.latest_minutes_inclusive
                if latest is None or received <= latest:
                    return None
                evidence.update({"latest_minutes_inclusive": latest})

            evidence.update({"selected_run": selected_run, "earliest_received_minutes": received})
            return DslRuleHit(rule_id=rule.id, anomaly_type=rule.anomaly_type.value, message=rule.message, evidence=evidence)

        raise ValueError(f"unsupported_rule_type:{rule.type}")


