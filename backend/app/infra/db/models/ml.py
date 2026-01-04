from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.models.common import CreatedAtMixin, UuidPrimaryKeyMixin


class InstitutionMlArtifact(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "institution_ml_artifact"
    __table_args__ = (
        UniqueConstraint(
            "institution_id",
            "as_of_date",
            "profile_config_version_id",
            "algorithm_version",
            name="uq_ml_artifact",
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

    algorithm_version: Mapped[str] = mapped_column(String(64), nullable=False, server_default="ml_mahalanobis_v1")
    artifact_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    artifact_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


