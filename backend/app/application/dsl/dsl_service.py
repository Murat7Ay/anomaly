from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.application.calendar_service import CalendarService
from app.application.audit.audit_service import AuditService
from app.domain.dsl.compiler import compile_rule_set
from app.domain.dsl.engine import DslEngine, DslEvaluationContext
from app.domain.dsl.schema import (
    DslRuleSet,
    DslRuleType,
    RunSelector,
    ScheduleSource,
)
from app.domain.profile.config import InstitutionProfileConfig, ScheduleSpec
from app.domain.profile.schedule_resolver import ScheduleResolver
from app.infra.repositories.calendar_repo import CalendarRepository
from app.infra.repositories.dsl_repo import DslConflictError, DslNotFoundError, DslRuleSetRepository
from app.infra.repositories.institution_repo import InstitutionRepository
from app.infra.repositories.profile_repo import ProfileRepository


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class DslValidationReport(BaseModel):
    schema_valid: bool
    compiled_hash: str | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    horizon_start: date | None = None
    horizon_end: date | None = None
    overlaps: list[dict[str, Any]] = Field(default_factory=list)
    rule_activation_summary: list[dict[str, Any]] = Field(default_factory=list)


class DslService:
    """
    Manages DSL rule set versions + validation + sandbox simulation.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._inst_repo = InstitutionRepository(db)
        self._profile_repo = ProfileRepository(db)
        self._dsl_repo = DslRuleSetRepository(db)
        self._calendar_service = CalendarService(CalendarRepository(db))
        self._resolver = ScheduleResolver(self._calendar_service)
        self._engine = DslEngine(calendar_service=self._calendar_service)
        self._audit = AuditService(db)

    def create_draft(
        self,
        *,
        institution_id: uuid.UUID,
        effective_from: date,
        created_by: str,
        rules_json: dict,
    ):
        self._inst_repo.get(institution_id)
        rule_set, compiled_hash, compiled_json, report = self.validate_rule_set(
            institution_id=institution_id, as_of_date=effective_from, rules_json=rules_json
        )
        # Store canonical rules_json as the persisted rules_json (not the raw input)
        canonical_rules_json = rule_set.canonical_json() if rule_set else compiled_json or rules_json
        row = self._dsl_repo.create_draft(
            institution_id=institution_id,
            effective_from=effective_from,
            created_by=created_by,
            rules_hash=compiled_hash or "INVALID",
            rules_json=canonical_rules_json,
            compiled_hash=compiled_hash,
            compiled_json=compiled_json,
            validation_report_json=report.model_dump(mode="json"),
        )
        self._audit.record(
            actor_type="USER",
            actor_id=created_by,
            action="DSL_DRAFT_CREATED",
            object_type="dsl_rule_set_version",
            object_id=str(row.id),
            before_hash=None,
            after_hash=row.rules_hash,
            message=None,
            metadata={"institution_id": str(institution_id), "effective_from": effective_from.isoformat()},
        )
        return row

    def list_versions(self, *, institution_id: uuid.UUID):
        self._inst_repo.get(institution_id)
        return self._dsl_repo.list_versions(institution_id)

    def get_version(self, *, institution_id: uuid.UUID, version_id: uuid.UUID):
        row = self._dsl_repo.get_version(version_id)
        if row.institution_id != institution_id:
            raise DslNotFoundError("dsl_version_not_found")
        return row

    def validate_existing_draft(self, *, institution_id: uuid.UUID, version_id: uuid.UUID, actor_id: str):
        row = self.get_version(institution_id=institution_id, version_id=version_id)
        if row.status.value != "DRAFT":
            raise DslConflictError("dsl_version_not_draft")
        rule_set, compiled_hash, compiled_json, report = self.validate_rule_set(
            institution_id=institution_id, as_of_date=row.effective_from, rules_json=row.rules_json
        )
        if not compiled_hash or not compiled_json or not rule_set:
            raise DslConflictError("dsl_schema_invalid")
        out = self._dsl_repo.update_compiled_artifacts(
            version_id=version_id,
            compiled_hash=compiled_hash,
            compiled_json=compiled_json,
            validation_report_json=report.model_dump(mode="json"),
        )
        self._audit.record(
            actor_type="USER",
            actor_id=actor_id,
            action="DSL_VALIDATED",
            object_type="dsl_rule_set_version",
            object_id=str(out.id),
            before_hash=out.rules_hash,
            after_hash=out.compiled_hash,
            message=None,
            metadata={"institution_id": str(institution_id), "version_num": out.version_num},
        )
        return out

    def approve_version(
        self,
        *,
        institution_id: uuid.UUID,
        version_id: uuid.UUID,
        approved_by: str,
        approval_reason: str | None,
    ):
        row = self.get_version(institution_id=institution_id, version_id=version_id)
        out = self._dsl_repo.approve_version(
            version_id=row.id,
            approved_by=approved_by,
            approval_reason=approval_reason,
            approved_at_utc=utc_now(),
        )
        self._audit.record(
            actor_type="USER",
            actor_id=approved_by,
            action="DSL_APPROVED",
            object_type="dsl_rule_set_version",
            object_id=str(out.id),
            before_hash=out.rules_hash,
            after_hash=out.compiled_hash,
            message=approval_reason,
            metadata={"institution_id": str(institution_id), "version_num": out.version_num},
        )
        return out

    def get_effective(self, *, institution_id: uuid.UUID, as_of_date: date):
        self._inst_repo.get(institution_id)
        return self._dsl_repo.effective_version(institution_id=institution_id, as_of_date=as_of_date)

    def validate_rule_set(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        rules_json: dict,
        horizon_days: int = 180,
    ) -> tuple[DslRuleSet | None, str | None, dict | None, DslValidationReport]:
        try:
            rule_set, compiled_hash, compiled_json = compile_rule_set(rules_json)
        except Exception as e:
            # Pydantic validation error; keep it deterministic by serializing to a string code
            report = DslValidationReport(schema_valid=False, errors=[str(e)])
            return None, None, None, report

        report = DslValidationReport(schema_valid=True, compiled_hash=compiled_hash)

        # Need profile context to resolve PROFILE schedule source and the institution holiday calendar.
        try:
            profile_version = self._profile_repo.effective_version(institution_id=institution_id, as_of_date=as_of_date)
        except Exception as e:
            report.errors.append(f"profile_missing:{e}")
            report.schema_valid = False
            return rule_set, compiled_hash, compiled_json, report

        profile = InstitutionProfileConfig.model_validate(profile_version.config_json)
        start = as_of_date
        end = as_of_date + timedelta(days=horizon_days)
        report.horizon_start = start
        report.horizon_end = end

        window = self._calendar_service.build_window_for_range(
            calendar_id=profile.calendar_id, start_date=start - timedelta(days=60), end_date=end + timedelta(days=60)
        )

        # Precompute activation sets per rule per run
        activation: dict[str, dict[str, set[date]]] = {}
        collisions_by_rule: dict[str, int] = {}

        for r in rule_set.rules:
            if not r.enabled:
                continue
            schedule = self._schedule_for_rule(profile=profile, rule=r)
            by_date = self._resolver.expected_by_date(schedule=schedule, window=window, start_date=start, end_date=end)
            collisions = sum(1 for d, occs in by_date.items() if len(occs) > 1)
            collisions_by_rule[r.id] = collisions

            def dates_for_run(run: str) -> set[date]:
                out: set[date] = set()
                for d, occs in by_date.items():
                    if any(o.expected_by_run == run for o in occs):
                        out.add(d)
                return out

            if r.type == DslRuleType.UNEXPECTED_LOAD_DAY:
                # Activation set is "non-expected days", which is the complement; for validation we keep expected sets.
                activation[r.id] = {"EXPECTED_ANY": set(by_date.keys())}
            else:
                run_sel = getattr(r, "params").run  # type: ignore[attr-defined]
                if run_sel == RunSelector.CURRENT:
                    activation[r.id] = {"AM_0900": dates_for_run("AM_0900"), "PM_1400": dates_for_run("PM_1400")}
                else:
                    sel = run_sel.value
                    activation[r.id] = {sel: dates_for_run(sel)}

        # Unreachable checks
        for rid, runs in activation.items():
            if all(len(s) == 0 for s in runs.values()):
                report.warnings.append(f"rule_unreachable_in_horizon:{rid}")
            if collisions_by_rule.get(rid, 0) > 0:
                report.warnings.append(f"schedule_collisions_in_horizon:{rid}:{collisions_by_rule[rid]}")

        # Overlap checks (within same run bucket)
        rule_ids = sorted(activation.keys())
        overlaps: list[dict[str, Any]] = []
        for i in range(len(rule_ids)):
            for j in range(i + 1, len(rule_ids)):
                a = rule_ids[i]
                b = rule_ids[j]
                for run_key, a_dates in activation[a].items():
                    b_dates = activation[b].get(run_key)
                    if not b_dates:
                        continue
                    inter = a_dates.intersection(b_dates)
                    if inter:
                        sample = sorted(inter)[:10]
                        overlaps.append(
                            {
                                "rule_a": a,
                                "rule_b": b,
                                "run": run_key,
                                "count": len(inter),
                                "sample_dates": [d.isoformat() for d in sample],
                            }
                        )
        report.overlaps = overlaps

        # Summary
        for r in rule_set.rules:
            if not r.enabled:
                continue
            report.rule_activation_summary.append(
                {
                    "rule_id": r.id,
                    "type": r.type,
                    "collisions_in_horizon": collisions_by_rule.get(r.id, 0),
                    "activation": {k: len(v) for k, v in activation.get(r.id, {}).items()},
                }
            )

        return rule_set, compiled_hash, compiled_json, report

    def sandbox(
        self,
        *,
        institution_id: uuid.UUID,
        rules_json: dict,
        test_cases: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # Compile schema first (sandbox should work even if profile is missing for "today").
        try:
            rule_set, compiled_hash, compiled_json = compile_rule_set(rules_json)
        except Exception as e:
            report = DslValidationReport(schema_valid=False, errors=[str(e)])
            return {"compiled_hash": None, "validation": report.model_dump(mode="json"), "results": []}

        # Optional richer validation (overlap/collision) using the first test case date if available.
        validate_date = date.today()
        if test_cases:
            try:
                validate_date = date.fromisoformat(test_cases[0]["as_of_date"])
            except Exception:
                validate_date = date.today()
        _, _, _, report = self.validate_rule_set(
            institution_id=institution_id, as_of_date=validate_date, rules_json=compiled_json
        )

        results: list[dict[str, Any]] = []
        for tc in test_cases:
            as_of = date.fromisoformat(tc["as_of_date"])
            run_type = tc["run_type"]

            try:
                profile_version = self._profile_repo.effective_version(institution_id=institution_id, as_of_date=as_of)
            except Exception as e:
                results.append(
                    {
                        "test_case": tc,
                        "error": f"profile_missing:{e}",
                        "triggered": False,
                        "hits": [],
                    }
                )
                continue
            profile = InstitutionProfileConfig.model_validate(profile_version.config_json)

            metrics_in = tc.get("metrics", {}) or {}
            metrics: dict[str, Decimal] = {}
            for k, v in metrics_in.items():
                metrics[k] = Decimal(str(v))

            ctx = DslEvaluationContext(
                institution_id=institution_id,
                as_of_date=as_of,
                run_type=run_type,
                has_load=bool(tc.get("has_load", False)),
                load_count=int(tc.get("load_count", 0)),
                earliest_received_minutes=tc.get("earliest_received_minutes"),
                metrics=metrics,
            )
            ev = self._engine.evaluate(rule_set=rule_set, profile=profile, ctx=ctx)
            results.append(
                {
                    "test_case": tc,
                    "triggered": ev.triggered,
                    "hits": [
                        {
                            "rule_id": h.rule_id,
                            "anomaly_type": h.anomaly_type,
                            "message": h.message,
                            "evidence": h.evidence,
                        }
                        for h in ev.hits
                    ],
                }
            )
        return {
            "compiled_hash": compiled_hash,
            "compiled_json": compiled_json,
            "validation": report.model_dump(mode="json"),
            "results": results,
        }

    def _schedule_for_rule(self, *, profile: InstitutionProfileConfig, rule) -> ScheduleSpec:
        ref = rule.params.schedule
        if ref.source == ScheduleSource.PROFILE:
            return profile.schedule
        assert ref.custom_schedule is not None
        return ref.custom_schedule


