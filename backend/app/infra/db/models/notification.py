from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import NotificationChannel, NotificationStatus, Severity
from app.infra.db.base import Base
from app.infra.db.models.common import CreatedAtMixin, UuidPrimaryKeyMixin


class NotificationEvent(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "notification_event"

    evaluation_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("daily_evaluation.id"), nullable=False, index=True
    )
    final_anomaly_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("final_anomaly.id"), nullable=True, index=True
    )

    channel: Mapped[NotificationChannel] = mapped_column(
        Enum(NotificationChannel, name="notification_channel"), nullable=False
    )
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, name="notification_status"), nullable=False, index=True
    )
    severity: Mapped[Severity] = mapped_column(Enum(Severity, name="severity"), nullable=False, index=True)

    to_addresses: Mapped[list[str]] = mapped_column(ARRAY(String(256)), nullable=False, server_default="{}")
    subject: Mapped[str] = mapped_column(String(256), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)

    sent_at_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)


