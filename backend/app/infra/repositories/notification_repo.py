from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.domain.enums import NotificationChannel, NotificationStatus, Severity
from app.domain.enums import RunType
from app.infra.db.models.evaluation import DailyEvaluation
from app.infra.db.models.notification import NotificationEvent


class NotificationRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_event(
        self,
        *,
        evaluation_id: uuid.UUID,
        final_anomaly_id: uuid.UUID | None,
        channel: NotificationChannel,
        severity: Severity,
        to_addresses: list[str],
        subject: str,
        body: str,
    ) -> NotificationEvent:
        row = NotificationEvent(
            evaluation_id=evaluation_id,
            final_anomaly_id=final_anomaly_id,
            channel=channel,
            status=NotificationStatus.PENDING,
            severity=severity,
            to_addresses=to_addresses,
            subject=subject,
            body=body,
            sent_at_utc=None,
            error_text=None,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def latest_for_evaluation(
        self, *, evaluation_id: uuid.UUID, severity: Severity, channel: NotificationChannel
    ) -> NotificationEvent | None:
        stmt = (
            select(NotificationEvent)
            .where(
                and_(
                    NotificationEvent.evaluation_id == evaluation_id,
                    NotificationEvent.severity == severity,
                    NotificationEvent.channel == channel,
                )
            )
            .order_by(NotificationEvent.created_at_utc.desc())
            .limit(1)
        )
        return self._db.execute(stmt).scalars().first()

    def latest_digest_for_subject(self, *, subject: str) -> NotificationEvent | None:
        stmt = (
            select(NotificationEvent)
            .where(NotificationEvent.subject == subject)
            .order_by(NotificationEvent.created_at_utc.desc())
            .limit(1)
        )
        return self._db.execute(stmt).scalars().first()

    def mark_sent(self, *, notification_id: uuid.UUID, sent_at_utc: datetime) -> NotificationEvent:
        row = self._db.get(NotificationEvent, notification_id)
        if not row:
            raise ValueError("notification_not_found")
        row.status = NotificationStatus.SENT
        row.sent_at_utc = sent_at_utc
        row.error_text = None
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def mark_failed(self, *, notification_id: uuid.UUID, sent_at_utc: datetime, error_text: str) -> NotificationEvent:
        row = self._db.get(NotificationEvent, notification_id)
        if not row:
            raise ValueError("notification_not_found")
        row.status = NotificationStatus.FAILED
        row.sent_at_utc = sent_at_utc
        row.error_text = error_text
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def list_warning_evaluations(self, *, as_of_date: date) -> list[DailyEvaluation]:
        stmt = select(DailyEvaluation).where(
            and_(
                DailyEvaluation.as_of_date == as_of_date,
                DailyEvaluation.run_type == RunType.PM_1400,
                DailyEvaluation.final_severity == Severity.WARNING,
                DailyEvaluation.is_anomaly.is_(True),
            )
        )
        return list(self._db.execute(stmt).scalars().all())


