from __future__ import annotations

from sqlalchemy import String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.models.common import CreatedAtMixin, UuidPrimaryKeyMixin


class AuditEvent(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "audit_event"

    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)  # USER|SYSTEM
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)

    action: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. PROFILE_APPROVED
    object_type: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. institution_profile_config_version
    object_id: Mapped[str] = mapped_column(String(128), nullable=False)

    before_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    after_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)

    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))


