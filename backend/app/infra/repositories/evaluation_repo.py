from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import DetectionLayer, RunType, Severity
from app.infra.db.models.evaluation import AnomalySignal, DailyEvaluation, EvaluationInputLoad, FinalAnomaly


class EvaluationConflictError(Exception):
    pass


class EvaluationRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_daily_evaluation(
        self, *, institution_id: uuid.UUID, as_of_date: date, run_type: RunType
    ) -> DailyEvaluation | None:
        stmt = select(DailyEvaluation).where(
            and_(
                DailyEvaluation.institution_id == institution_id,
                DailyEvaluation.as_of_date == as_of_date,
                DailyEvaluation.run_type == run_type,
            )
        )
        return self._db.execute(stmt).scalars().first()

    def get_by_id(self, evaluation_id: uuid.UUID) -> DailyEvaluation | None:
        return self._db.get(DailyEvaluation, evaluation_id)

    def list_signals(self, evaluation_id: uuid.UUID) -> list[AnomalySignal]:
        stmt = select(AnomalySignal).where(AnomalySignal.evaluation_id == evaluation_id).order_by(
            AnomalySignal.created_at_utc.asc()
        )
        return list(self._db.execute(stmt).scalars().all())

    def create_daily_evaluation(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        run_type: RunType,
        run_at_utc: datetime,
        system_version: str,
        profile_config_version_id: uuid.UUID,
        profile_config_hash: str,
        dsl_rule_set_version_id: uuid.UUID,
        dsl_rules_hash: str,
        profile_stats_snapshot_id: uuid.UUID | None,
        profile_stats_hash: str | None,
        calendar_context_json: dict,
        input_aggregate_json: dict,
        computed_context_json: dict,
        layer_results_json: dict,
        is_anomaly: bool,
        final_severity: Severity,
        anomaly_types: list[str],
    ) -> DailyEvaluation:
        row = DailyEvaluation(
            institution_id=institution_id,
            as_of_date=as_of_date,
            run_type=run_type,
            run_at_utc=run_at_utc,
            system_version=system_version,
            profile_config_version_id=profile_config_version_id,
            profile_config_hash=profile_config_hash,
            dsl_rule_set_version_id=dsl_rule_set_version_id,
            dsl_rules_hash=dsl_rules_hash,
            profile_stats_snapshot_id=profile_stats_snapshot_id,
            profile_stats_hash=profile_stats_hash,
            calendar_context_json=calendar_context_json,
            input_aggregate_json=input_aggregate_json,
            computed_context_json=computed_context_json,
            layer_results_json=layer_results_json,
            is_anomaly=is_anomaly,
            final_severity=final_severity,
            anomaly_types=anomaly_types,
        )
        self._db.add(row)
        try:
            self._db.commit()
        except IntegrityError as e:
            self._db.rollback()
            raise EvaluationConflictError("daily_evaluation_conflict") from e
        self._db.refresh(row)
        return row

    def add_input_loads(self, *, evaluation_id: uuid.UUID, load_batch_ids: Iterable[uuid.UUID]) -> None:
        rows = [EvaluationInputLoad(evaluation_id=evaluation_id, load_batch_id=lb) for lb in load_batch_ids]
        self._db.add_all(rows)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            # idempotency: ignore duplicates

    def add_signals(self, *, evaluation_id: uuid.UUID, signals: list[dict]) -> None:
        rows: list[AnomalySignal] = []
        for s in signals:
            rows.append(
                AnomalySignal(
                    evaluation_id=evaluation_id,
                    layer=DetectionLayer(s["layer"]),
                    signal_type=s["signal_type"],
                    metric_id=s.get("metric_id"),
                    occurrence_id=s.get("occurrence_id"),
                    is_triggered=bool(s["is_triggered"]),
                    severity_suggested=Severity(s["severity_suggested"]),
                    score=s.get("score"),
                    threshold_low=s.get("threshold_low"),
                    threshold_high=s.get("threshold_high"),
                    explanation_json=s.get("explanation_json", {}),
                )
            )
        self._db.add_all(rows)
        self._db.commit()

    def upsert_final_anomaly(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        evaluation_id: uuid.UUID,
        is_anomaly: bool,
        severity: Severity,
        anomaly_types: list[str],
        summary: str | None,
    ) -> FinalAnomaly:
        existing = self._db.execute(
            select(FinalAnomaly).where(
                and_(FinalAnomaly.institution_id == institution_id, FinalAnomaly.as_of_date == as_of_date)
            )
        ).scalars().first()
        if existing:
            existing.current_evaluation_id = evaluation_id
            existing.version_num = int(existing.version_num) + 1
            existing.is_anomaly = is_anomaly
            existing.severity = severity
            existing.anomaly_types = anomaly_types
            existing.summary = summary
            self._db.add(existing)
            self._db.commit()
            self._db.refresh(existing)
            return existing

        row = FinalAnomaly(
            institution_id=institution_id,
            as_of_date=as_of_date,
            current_evaluation_id=evaluation_id,
            version_num=1,
            is_anomaly=is_anomaly,
            severity=severity,
            anomaly_types=anomaly_types,
            summary=summary,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row


