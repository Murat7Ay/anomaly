from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import VersionStatus
from app.infra.db.base import Base
from app.infra.db.models.common import CreatedAtMixin, UuidPrimaryKeyMixin


class InstitutionProfileConfigVersion(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "institution_profile_config_version"
    __table_args__ = (
        UniqueConstraint("institution_id", "version_num", name="uq_profile_versionnum"),
    )

    institution_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institution.id"), nullable=False, index=True
    )
    version_num: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[VersionStatus] = mapped_column(
        Enum(VersionStatus, name="version_status"), nullable=False, index=True
    )

    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    config_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    created_by: Mapped[str] = mapped_column(String(128), nullable=False)

    approved_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)


class InstitutionProfileStatsSnapshot(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "institution_profile_stats_snapshot"
    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "as_of_date",
            "profile_config_version_id",
            name="uq_profile_stats_snapshot",
        ),
    )

    institution_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institution.id"), nullable=False, index=True
    )
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    profile_config_version_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("institution_profile_config_version.id"),
        nullable=False,
        index=True,
    )

    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False, server_default="v1")
    snapshot_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    data_cutoff_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


