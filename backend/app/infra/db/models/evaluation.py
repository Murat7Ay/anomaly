from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import DetectionLayer, RunType, Severity
from app.infra.db.base import Base
from app.infra.db.models.common import CreatedAtMixin, UuidPrimaryKeyMixin


class DailyEvaluation(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "daily_evaluation"
    __table_args__ = (
        UniqueConstraint("institution_id", "as_of_date", "run_type", name="uq_daily_eval"),
        Index("ix_daily_eval_inst_date", "institution_id", "as_of_date"),
    )

    institution_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institution.id"), nullable=False, index=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    run_type: Mapped[RunType] = mapped_column(Enum(RunType, name="run_type"), nullable=False, index=True)
    run_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    system_version: Mapped[str] = mapped_column(String(64), nullable=False, server_default="dev")

    profile_config_version_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institution_profile_config_version.id"),
        nullable=False,
        index=True,
    )
    profile_config_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    dsl_rule_set_version_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("dsl_rule_set_version.id"), nullable=False, index=True
    )
    dsl_rules_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)

    profile_stats_snapshot_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institution_profile_stats_snapshot.id"),
        nullable=True,
        index=True,
    )
    profile_stats_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    calendar_context_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    input_aggregate_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    computed_context_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    layer_results_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    final_severity: Mapped[Severity] = mapped_column(
        Enum(Severity, name="severity"), nullable=False, index=True, server_default=Severity.NONE.value
    )
    anomaly_types: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, server_default="{}")


class EvaluationInputLoad(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "evaluation_input_load"
    __table_args__ = (
        UniqueConstraint("evaluation_id", "load_batch_id", name="uq_eval_load"),
        Index("ix_eval_load_eval", "evaluation_id"),
        Index("ix_eval_load_batch", "load_batch_id"),
    )

    evaluation_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("daily_evaluation.id"), nullable=False
    )
    load_batch_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("load_batch.id"), nullable=False)


class AnomalySignal(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "anomaly_signal"
    __table_args__ = (Index("ix_signal_eval_layer", "evaluation_id", "layer"),)

    evaluation_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("daily_evaluation.id"), nullable=False, index=True
    )
    layer: Mapped[DetectionLayer] = mapped_column(
        Enum(DetectionLayer, name="detection_layer"), nullable=False, index=True
    )

    signal_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # e.g. NO_DATA, HIGH_VOLUME
    metric_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occurrence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    is_triggered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    severity_suggested: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    threshold_low: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    threshold_high: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)

    explanation_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


class FinalAnomaly(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "final_anomaly"
    __table_args__ = (UniqueConstraint("institution_id", "as_of_date", name="uq_final_anomaly"),)

    institution_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institution.id"), nullable=False, index=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    current_evaluation_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("daily_evaluation.id"), nullable=False, index=True
    )

    version_num: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    is_anomaly: Mapped[bool] = mapped_column(Boolean, nullable=False)
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), nullable=False, index=True)
    anomaly_types: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, server_default="{}")
    summary: Mapped[str | None] = mapped_column(String(512), nullable=True)


