from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infra.db.base import Base
from app.infra.db.models.common import CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin


class Institution(Base, UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "institution"

    external_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    # Optional convenience fields; authoritative values live in the effective profile config.
    default_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    default_calendar_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_calendar.id"), nullable=True
    )


