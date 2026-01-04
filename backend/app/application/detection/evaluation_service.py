from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.application.calendar_service import CalendarService
from app.application.ml.ml_engine import MlEngineV1, MlInsufficientDataError
from app.application.stats.stats_engine import StatsEngineV1
from app.domain.dsl.compiler import compile_rule_set
from app.domain.dsl.engine import DslEvaluationContext, DslEngine
from app.domain.dsl.schema import DslRuleSet
from app.domain.enums import RunType, Severity
from app.domain.profile.config import InstitutionProfileConfig
from app.domain.profile.schedule_resolver import ScheduleResolver
from app.infra.repositories.calendar_repo import CalendarRepository
from app.infra.repositories.dsl_repo import DslNotFoundError, DslRuleSetRepository
from app.infra.repositories.evaluation_repo import EvaluationConflictError, EvaluationRepository
from app.infra.repositories.institution_repo import InstitutionRepository
from app.infra.repositories.load_repo import LoadRepository
from app.infra.repositories.profile_repo import ProfileConflictError, ProfileNotFoundError, ProfileRepository
from app.application.profile.profile_service import ProfileService


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _run_type_str(rt: RunType) -> str:
    return rt.value if hasattr(rt, "value") else str(rt)


class EvaluationService:
    """
    Detection-core orchestration.

    Produces a persisted DailyEvaluation record per institution per day per run, and maintains a single
    FinalAnomaly record per institution per day pointing at the latest evaluation.
    """

    SYSTEM_VERSION = "dev"

    def __init__(
        self,
        db: Session,
        *,
        stats_engine: Any | None = None,
        ml_engine: Any | None = None,
    ) -> None:
        self._db = db
        self._inst_repo = InstitutionRepository(db)
        self._profile_repo = ProfileRepository(db)
        self._dsl_repo = DslRuleSetRepository(db)
        self._load_repo = LoadRepository(db)
        self._eval_repo = EvaluationRepository(db)
        self._calendar_service = CalendarService(CalendarRepository(db))
        self._dsl_engine = DslEngine(calendar_service=self._calendar_service)
        self._stats_engine = stats_engine or StatsEngineV1(
            schedule_resolver=ScheduleResolver(self._calendar_service)
        )
        self._ml_engine = ml_engine or MlEngineV1(
            db,
            calendar_service=self._calendar_service,
            schedule_resolver=ScheduleResolver(self._calendar_service),
        )

    def evaluate_institution_day(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        run_type: RunType,
        profile_version_override: Any | None = None,
        dsl_version_override: Any | None = None,
    ) -> dict[str, Any]:
        # Idempotency: do not recompute if already persisted for this run.
        existing = self._eval_repo.get_daily_evaluation(
            institution_id=institution_id, as_of_date=as_of_date, run_type=run_type
        )
        if existing:
            if run_type in {RunType.AM_0900, RunType.PM_1400, RunType.MANUAL}:
                # Keep FinalAnomaly pointing to the latest evaluation (e.g. PM run overrides AM run).
                self._eval_repo.upsert_final_anomaly(
                    institution_id=institution_id,
                    as_of_date=as_of_date,
                    evaluation_id=existing.id,
                    is_anomaly=existing.is_anomaly,
                    severity=existing.final_severity,
                    anomaly_types=list(existing.anomaly_types),
                    summary=None,
                )
            return {"evaluation_id": str(existing.id), "status": "EXISTS"}

        # Load institution + effective profile + effective DSL
        inst = self._inst_repo.get(institution_id)
        profile_version = profile_version_override or self._profile_repo.effective_version(
            institution_id=institution_id, as_of_date=as_of_date
        )
        profile = InstitutionProfileConfig.model_validate(profile_version.config_json)

        dsl_version = dsl_version_override or self._dsl_repo.effective_version(
            institution_id=institution_id, as_of_date=as_of_date
        )
        if dsl_version.compiled_json:
            rule_set = DslRuleSet.model_validate(dsl_version.compiled_json)
            dsl_hash = dsl_version.compiled_hash or dsl_version.rules_hash
        else:
            rule_set, dsl_hash, _compiled_json = compile_rule_set(dsl_version.rules_json)

        # Aggregate loads for the day (institution local date)
        loads = self._load_repo.list_by_local_date_range(
            institution_id=institution_id,
            start_date=as_of_date,
            end_date_exclusive=as_of_date + timedelta(days=1),
        )
        agg = self._aggregate_day(profile=profile, load_batches=loads)

        # Calendar context for audit/explainability
        cal_window = self._calendar_service.build_window_for_range(
            calendar_id=profile.calendar_id,
            start_date=as_of_date - timedelta(days=60),
            end_date=as_of_date + timedelta(days=60),
        )
        calendar_ctx = {
            "as_of_date": as_of_date.isoformat(),
            "is_weekend": as_of_date.weekday() >= 5,
            "is_holiday": cal_window.is_holiday(as_of_date),
            "is_business_day": cal_window.is_business_day(as_of_date),
            "calendar_id": str(profile.calendar_id),
        }

        # Layer 1: DSL (final override)
        dsl_ctx = DslEvaluationContext(
            institution_id=institution_id,
            as_of_date=as_of_date,
            run_type=_run_type_str(run_type),
            has_load=agg["has_load"],
            load_count=agg["load_count"],
            earliest_received_minutes=agg["earliest_received_minutes"],
            metrics=agg["metrics"],
        )
        dsl_result = self._dsl_engine.evaluate(rule_set=rule_set, profile=profile, ctx=dsl_ctx)

        is_anomaly = False
        severity = Severity.NONE
        anomaly_types: list[str] = []
        signals: list[dict[str, Any]] = []
        profile_stats_snapshot_id: uuid.UUID | None = None
        profile_stats_hash: str | None = None
        layer_results: dict[str, Any] = {
            "dsl": {"triggered": dsl_result.triggered, "hits": []},
            "stats": {"status": "SKIPPED", "reason": None, "signals": []},
            "ml": {"status": "SKIPPED", "reason": None, "signals": []},
        }

        if dsl_result.triggered:
            is_anomaly = True
            severity = Severity.CRITICAL
            anomaly_types = sorted({h.anomaly_type for h in dsl_result.hits})
            layer_results["dsl"]["hits"] = [
                {"rule_id": h.rule_id, "anomaly_type": h.anomaly_type, "message": h.message, "evidence": h.evidence}
                for h in dsl_result.hits
            ]
            for h in dsl_result.hits:
                signals.append(
                    {
                        "layer": "DSL",
                        "signal_type": h.anomaly_type,
                        "metric_id": None,
                        "occurrence_id": None,
                        "is_triggered": True,
                        "severity_suggested": "CRITICAL",
                        "score": None,
                        "threshold_low": None,
                        "threshold_high": None,
                        "explanation_json": {"rule_id": h.rule_id, "message": h.message, "evidence": h.evidence},
                    }
                )
        else:
            # Enforce new-institution policy: first N days DSL-only (no Stats/ML decisioning).
            stats_enable_date = profile.maturity_policy.first_seen_date + timedelta(
                days=profile.maturity_policy.stats_enabled_after_days
            )
            ml_enable_date = profile.maturity_policy.first_seen_date + timedelta(
                days=profile.maturity_policy.ml_enabled_after_days
            )
            stats_enabled = as_of_date >= stats_enable_date
            ml_enabled = as_of_date >= ml_enable_date

            stats_signals: list[dict[str, Any]] = []
            stats_snapshot_json: dict[str, Any] | None = None
            if not stats_enabled:
                layer_results["stats"]["reason"] = "maturity_gate"
            elif self._stats_engine is None:
                layer_results["stats"]["reason"] = "engine_not_configured"
            else:
                layer_results["stats"]["status"] = "DONE"
                try:
                    snap = ProfileService(self._db).get_or_compute_stats_snapshot(
                        institution_id=institution_id,
                        as_of_date=as_of_date,
                        profile_version_id=profile_version.id,
                    )
                    profile_stats_snapshot_id = snap.id
                    profile_stats_hash = snap.snapshot_hash
                    stats_snapshot_json = snap.snapshot_json
                except ProfileConflictError as e:
                    layer_results["stats"]["status"] = "SKIPPED"
                    layer_results["stats"]["reason"] = str(e)
                if stats_snapshot_json is not None:
                    stats_signals = list(
                        self._stats_engine.evaluate(
                            profile=profile,
                            as_of_date=as_of_date,
                            run_type=_run_type_str(run_type),
                            daily_aggregate=agg,
                            calendar_window=cal_window,
                            stats_snapshot_json=stats_snapshot_json,
                        )
                    )
                layer_results["stats"]["signals"] = stats_signals

            ml_signals: list[dict[str, Any]] = []
            if not ml_enabled:
                layer_results["ml"]["reason"] = "maturity_gate"
            elif self._ml_engine is None:
                layer_results["ml"]["reason"] = "engine_not_configured"
            else:
                layer_results["ml"]["status"] = "DONE"
                try:
                    ml_signals = list(
                        self._ml_engine.evaluate(
                            institution_id=institution_id,
                            profile_config_version_id=profile_version.id,
                            profile=profile,
                            as_of_date=as_of_date,
                            run_type=_run_type_str(run_type),
                            daily_aggregate=agg,
                            calendar_window=cal_window,
                            stats_signals=stats_signals,
                        )
                    )
                    layer_results["ml"]["signals"] = ml_signals
                except MlInsufficientDataError as e:
                    layer_results["ml"]["status"] = "SKIPPED"
                    layer_results["ml"]["reason"] = str(e)

            # Aggregate non-DSL signals (WARNING/CRITICAL); CRITICAL if any signal suggests CRITICAL.
            all_signals = [s for s in stats_signals + ml_signals if s.get("is_triggered")]
            if all_signals:
                is_anomaly = True
                if any(s.get("severity_suggested") == "CRITICAL" for s in all_signals):
                    severity = Severity.CRITICAL
                else:
                    severity = Severity.WARNING
                anomaly_types = sorted({s.get("signal_type") for s in all_signals if s.get("signal_type")})
                signals.extend(all_signals)

        input_agg_json = {
            "institution_id": str(institution_id),
            "external_code": inst.external_code,
            "load_batch_ids": [str(lb.id) for lb in loads],
            "has_load": agg["has_load"],
            "load_count": agg["load_count"],
            "earliest_received_minutes": agg["earliest_received_minutes"],
            "metrics": {k: str(v) for k, v in agg["metrics"].items()},
        }

        computed_ctx_json = {
            "profile_version_id": str(profile_version.id),
            "profile_hash": profile_version.config_hash,
            "dsl_version_id": str(dsl_version.id),
            "dsl_hash": dsl_hash,
            "profile_stats_snapshot_id": str(profile_stats_snapshot_id) if profile_stats_snapshot_id else None,
            "profile_stats_hash": profile_stats_hash,
            "maturity": {
                "first_seen_date": profile.maturity_policy.first_seen_date.isoformat(),
                "stats_enabled_after_days": profile.maturity_policy.stats_enabled_after_days,
                "ml_enabled_after_days": profile.maturity_policy.ml_enabled_after_days,
            },
        }

        try:
            ev = self._eval_repo.create_daily_evaluation(
                institution_id=institution_id,
                as_of_date=as_of_date,
                run_type=run_type,
                run_at_utc=utc_now(),
                system_version=self.SYSTEM_VERSION,
                profile_config_version_id=profile_version.id,
                profile_config_hash=profile_version.config_hash,
                dsl_rule_set_version_id=dsl_version.id,
                dsl_rules_hash=dsl_hash,
                profile_stats_snapshot_id=profile_stats_snapshot_id,
                profile_stats_hash=profile_stats_hash,
                calendar_context_json=calendar_ctx,
                input_aggregate_json=input_agg_json,
                computed_context_json=computed_ctx_json,
                layer_results_json=layer_results,
                is_anomaly=is_anomaly,
                final_severity=severity,
                anomaly_types=anomaly_types,
            )
        except EvaluationConflictError:
            # Another worker beat us; return existing.
            ev2 = self._eval_repo.get_daily_evaluation(
                institution_id=institution_id, as_of_date=as_of_date, run_type=run_type
            )
            if ev2:
                return {"evaluation_id": str(ev2.id), "status": "RACE_EXISTING"}
            raise

        # Link inputs and signals
        self._eval_repo.add_input_loads(evaluation_id=ev.id, load_batch_ids=[lb.id for lb in loads])
        if signals:
            self._eval_repo.add_signals(evaluation_id=ev.id, signals=signals)

        # Maintain single FinalAnomaly per institution/day
        if run_type in {RunType.AM_0900, RunType.PM_1400, RunType.MANUAL}:
            self._eval_repo.upsert_final_anomaly(
                institution_id=institution_id,
                as_of_date=as_of_date,
                evaluation_id=ev.id,
                is_anomaly=is_anomaly,
                severity=severity,
                anomaly_types=anomaly_types,
                summary=None,
            )

        return {"evaluation_id": str(ev.id), "status": "CREATED", "is_anomaly": is_anomaly, "severity": severity.value}

    def _aggregate_day(self, *, profile: InstitutionProfileConfig, load_batches) -> dict[str, Any]:
        tz = ZoneInfo(profile.timezone)
        metrics: dict[str, Decimal] = {}
        earliest_minutes: int | None = None

        for lb in load_batches:
            if lb.debt_item_count is not None:
                metrics["debt_item_count"] = metrics.get("debt_item_count", Decimal(0)) + Decimal(int(lb.debt_item_count))
            if lb.total_debt_amount is not None:
                metrics["total_debt_amount"] = metrics.get("total_debt_amount", Decimal(0)) + Decimal(lb.total_debt_amount)
            if lb.unique_customer_count is not None:
                # Conservative aggregation: take max to avoid double counting across multiple batches
                v = Decimal(int(lb.unique_customer_count))
                cur = metrics.get("unique_customer_count")
                metrics["unique_customer_count"] = v if cur is None else max(cur, v)

            if isinstance(lb.metrics_json, dict):
                for k, raw_v in lb.metrics_json.items():
                    try:
                        dv = Decimal(str(raw_v))
                    except Exception:
                        continue
                    metrics[k] = metrics.get(k, Decimal(0)) + dv

            if lb.received_at_utc is not None:
                local_dt = lb.received_at_utc.astimezone(tz)
                m = local_dt.hour * 60 + local_dt.minute
                earliest_minutes = m if earliest_minutes is None else min(earliest_minutes, m)

        return {
            "has_load": len(load_batches) > 0,
            "load_count": len(load_batches),
            "earliest_received_minutes": earliest_minutes,
            "metrics": metrics,
        }


