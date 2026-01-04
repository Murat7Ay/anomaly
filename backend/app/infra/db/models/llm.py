from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import LlmStatus
from app.infra.db.base import Base
from app.infra.db.models.common import CreatedAtMixin, UuidPrimaryKeyMixin


class LlmExplanation(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "llm_explanation"

    evaluation_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("daily_evaluation.id"), nullable=False, index=True
    )

    status: Mapped[LlmStatus] = mapped_column(Enum(LlmStatus, name="llm_status"), nullable=False)

    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    prompt_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)

    response_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


