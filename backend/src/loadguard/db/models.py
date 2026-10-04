"""PostgreSQL schema. Postgres is the only datastore (also the job queue): one thing to operate and back up."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

TZ = DateTime(timezone=True)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONB, list[Any]: JSONB, datetime: TZ}


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class User(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(16))  # ANALYST | APPROVER | ADMIN
    email: Mapped[str | None] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Holiday(Base):
    __tablename__ = "holidays"
    calendar_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    half_day: Mapped[bool] = mapped_column(Boolean, default=False)


class Institution(Base):
    __tablename__ = "institutions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    sector: Mapped[str] = mapped_column(String(32))
    tier: Mapped[int] = mapped_column(Integer)  # 1 = most critical
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    contact_email: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class ContractVersion(Base):
    __tablename__ = "contract_versions"
    __table_args__ = (UniqueConstraint("institution_id", "version"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    institution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("institutions.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24))  # DRAFT|PENDING_APPROVAL|APPROVED|REJECTED|WITHDRAWN
    effective_from: Mapped[date] = mapped_column(Date)
    spec: Mapped[dict[str, Any]]
    spec_hash: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(24), default="MANUAL")  # MANUAL|INFERRED|TUNING|AI_ASSIST|SEED
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    submitted_at: Mapped[datetime | None]
    decided_by: Mapped[str | None] = mapped_column(String(64))
    decided_at: Mapped[datetime | None]
    decision_note: Mapped[str | None] = mapped_column(Text)
    backtest: Mapped[dict[str, Any] | None]


class Load(Base):
    __tablename__ = "loads"
    __table_args__ = (
        UniqueConstraint("institution_id", "external_id"),
        Index("ix_loads_inst_received", "institution_id", "received_at"),
        Index("ix_loads_inst_hash", "institution_id", "content_hash"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    institution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("institutions.id"))
    external_id: Mapped[str] = mapped_column(String(128))  # idempotency key from the integration
    received_at: Mapped[datetime]
    source: Mapped[str] = mapped_column(String(16))  # SFTP | API | SIM
    file_name: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(128))
    slot_hint: Mapped[str | None] = mapped_column(String(48))
    record_count: Mapped[int] = mapped_column(BigInteger)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    customer_count: Mapped[int] = mapped_column(BigInteger)
    zero_amount_count: Mapped[int] = mapped_column(BigInteger, default=0)
    negative_amount_count: Mapped[int] = mapped_column(BigInteger, default=0)
    duplicate_record_count: Mapped[int] = mapped_column(BigInteger, default=0)
    max_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 2))
    occurrence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("occurrences.id"), index=True)
    assignment_reason: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Occurrence(Base):
    """One expected (or unexpected) delivery: the unit of evaluation, history and case management."""

    __tablename__ = "occurrences"
    __table_args__ = (
        UniqueConstraint("institution_id", "slot_key", "business_date"),
        Index("ix_occ_status_deadline", "status", "deadline_utc"),
        Index("ix_occ_date", "business_date"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    institution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("institutions.id"))
    slot_key: Mapped[str] = mapped_column(String(48))
    business_date: Mapped[date] = mapped_column(Date)
    expected: Mapped[bool] = mapped_column(Boolean)
    window_start_utc: Mapped[datetime | None]
    deadline_utc: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(String(16))
    first_received_at: Mapped[datetime | None]
    load_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict)
    baselines: Mapped[dict[str, Any]] = mapped_column(default=dict)
    findings: Mapped[list[Any]] = mapped_column(default=list)
    max_severity: Mapped[str | None] = mapped_column(String(16))
    contract_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contract_versions.id"))
    spec_hash: Mapped[str | None] = mapped_column(String(64))
    evaluated_at: Mapped[datetime | None]
    excluded_from_baseline: Mapped[bool] = mapped_column(Boolean, default=False)
    regime_break: Mapped[bool] = mapped_column(Boolean, default=False)


class Evaluation(Base):
    """Append-only decision record: inputs, versions and outputs of every evaluation (audit/replay)."""

    __tablename__ = "evaluations"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    occurrence_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("occurrences.id"), index=True)
    trigger: Mapped[str] = mapped_column(String(24))  # LOAD | DEADLINE_SWEEP | RELABEL | BACKFILL
    evaluated_at: Mapped[datetime]
    engine_version: Mapped[str] = mapped_column(String(32))
    contract_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("contract_versions.id"))
    spec_hash: Mapped[str | None] = mapped_column(String(64))
    inputs: Mapped[dict[str, Any]]
    result: Mapped[dict[str, Any]]


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index(
            "uq_incident_open_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=text("status <> 'RESOLVED'"),
        ),
        Index("ix_incident_status_priority", "status", "priority"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    number: Mapped[int] = mapped_column(BigInteger, Identity(start=1001), unique=True)
    kind: Mapped[str] = mapped_column(String(16), default="OCCURRENCE")  # OCCURRENCE | SYSTEMIC
    institution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("institutions.id"), index=True)
    occurrence_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("occurrences.id"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("incidents.id"))
    fingerprint: Mapped[str] = mapped_column(String(160))
    category: Mapped[str] = mapped_column(String(16))
    codes: Mapped[list[Any]] = mapped_column(default=list)
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16))  # OPEN | ACKNOWLEDGED | RESOLVED
    severity: Mapped[str] = mapped_column(String(16))
    priority: Mapped[str] = mapped_column(String(4))
    impact_customers: Mapped[float | None]
    impact_amount: Mapped[float | None]
    opened_at: Mapped[datetime]
    updated_at: Mapped[datetime]
    acknowledged_at: Mapped[datetime | None]
    acknowledged_by: Mapped[str | None] = mapped_column(String(64))
    assignee: Mapped[str | None] = mapped_column(String(64))
    resolved_at: Mapped[datetime | None]
    resolved_by: Mapped[str | None] = mapped_column(String(64))
    resolution: Mapped[str | None] = mapped_column(String(24))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    suppressed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("suppressions.id"))

    events: Mapped[list[IncidentEvent]] = relationship(order_by="IncidentEvent.at", lazy="raise")


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    at: Mapped[datetime]
    actor: Mapped[str] = mapped_column(String(64))  # username or "system"
    kind: Mapped[str] = mapped_column(String(24))
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Suppression(Base):
    """Planned maintenance / known events: findings are still recorded, but nobody is paged."""

    __tablename__ = "suppressions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    institution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("institutions.id"))
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    reason: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_ready", "status", "run_at"),)
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(48))
    payload: Mapped[dict[str, Any]]
    status: Mapped[str] = mapped_column(String(16), default="QUEUED")
    run_at: Mapped[datetime]
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None]
    dedupe_key: Mapped[str | None] = mapped_column(String(160), unique=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None]


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime]
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(default=dict)


class AiInteraction(Base):
    """Every model call is recorded: who asked, what was sent, what came back, whether it was grounded."""

    __tablename__ = "ai_interactions"
    __table_args__ = (Index("ix_ai_entity", "entity_type", "entity_id"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    at: Mapped[datetime]
    actor: Mapped[str] = mapped_column(String(64))
    purpose: Mapped[str] = mapped_column(String(32))  # INCIDENT_BRIEF | CONTRACT_ASSIST
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(96))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str] = mapped_column(String(64))
    request: Mapped[dict[str, Any]]
    response: Mapped[dict[str, Any] | None]
    grounding: Mapped[dict[str, Any] | None]
    status: Mapped[str] = mapped_column(String(16))  # OK | FALLBACK | ERROR
    latency_ms: Mapped[int | None]


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    incident_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("incidents.id"), index=True)
    channel: Mapped[str] = mapped_column(String(16))
    target: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime]
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)


class SimPlannedLoad(Base):
    """Demo only: future synthetic deliveries the worker ingests when their time comes."""

    __tablename__ = "sim_planned_loads"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    institution_code: Mapped[str] = mapped_column(String(32))
    due_at: Mapped[datetime] = mapped_column(index=True)
    payload: Mapped[dict[str, Any]]
    ingested: Mapped[bool] = mapped_column(Boolean, default=False)


class SimTruth(Base):
    """Demo only: ground truth of injected anomalies, to show measured detector quality."""

    __tablename__ = "sim_truths"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    institution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("institutions.id"))
    slot_key: Mapped[str] = mapped_column(String(48))
    business_date: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(32))
