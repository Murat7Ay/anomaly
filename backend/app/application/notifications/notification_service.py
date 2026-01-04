from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.domain.enums import NotificationChannel, Severity
from app.infra.repositories.evaluation_repo import EvaluationRepository
from app.infra.repositories.notification_repo import NotificationRepository
from app.infra.notifications.email_sender import EmailPayload, SmtpEmailSender

log = get_logger(__name__)


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _split_recipients(value: str) -> list[str]:
    out: list[str] = []
    for part in (value or "").split(","):
        p = part.strip()
        if p:
            out.append(p)
    return out


class NotificationService:
    """
    Notification routing driven by persisted evaluation records.

    - CRITICAL: immediate per-evaluation alert
    - WARNING: daily digest email (grouped)
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._settings = get_settings()
        self._eval_repo = EvaluationRepository(db)
        self._repo = NotificationRepository(db)
        self._email = SmtpEmailSender()

    def process_evaluation(self, *, evaluation_id: uuid.UUID) -> dict[str, Any]:
        ev = self._eval_repo.get_by_id(evaluation_id)
        if not ev:
            raise ValueError("evaluation_not_found")

        if not ev.is_anomaly:
            return {"status": "SKIPPED", "reason": "not_anomaly"}

        if ev.final_severity != Severity.CRITICAL:
            return {"status": "SKIPPED", "reason": "not_critical"}

        existing = self._repo.latest_for_evaluation(
            evaluation_id=ev.id, severity=Severity.CRITICAL, channel=NotificationChannel.EMAIL
        )
        if existing and existing.status.value == "SENT":
            return {"status": "SKIPPED", "reason": "already_sent", "notification_id": str(existing.id)}

        recipients = _split_recipients(self._settings.critical_alert_recipients)
        subject = f"[CRITICAL] DebtLoad anomaly {ev.as_of_date.isoformat()} ({','.join(ev.anomaly_types)})"
        body = (
            f"CRITICAL anomaly detected.\n\n"
            f"Institution: {ev.institution_id}\n"
            f"Date: {ev.as_of_date.isoformat()}\n"
            f"Run: {ev.run_type}\n"
            f"Types: {', '.join(ev.anomaly_types)}\n"
            f"EvaluationId: {ev.id}\n"
            f"Severity: {ev.final_severity}\n\n"
            f"LayerResults:\n{ev.layer_results_json}\n"
        )

        event = self._repo.create_event(
            evaluation_id=ev.id,
            final_anomaly_id=None,
            channel=NotificationChannel.EMAIL,
            severity=Severity.CRITICAL,
            to_addresses=recipients,
            subject=subject,
            body=body,
        )
        try:
            self._email.send(EmailPayload(to_addresses=recipients, subject=subject, body=body))
            self._repo.mark_sent(notification_id=event.id, sent_at_utc=utc_now())
            return {"status": "SENT", "notification_id": str(event.id)}
        except Exception as e:
            self._repo.mark_failed(notification_id=event.id, sent_at_utc=utc_now(), error_text=str(e))
            log.error("notification_send_failed", notification_id=str(event.id), error=str(e))
            return {"status": "FAILED", "notification_id": str(event.id), "error": str(e)}

    def send_warning_digest(self, *, as_of_date: date) -> dict[str, Any]:
        recipients = _split_recipients(self._settings.warning_digest_recipients)
        evals = self._repo.list_warning_evaluations(as_of_date=as_of_date)
        if not evals:
            return {"status": "SKIPPED", "reason": "no_warning_anomalies"}

        subject = f"[WARNING] DebtLoad anomaly digest {as_of_date.isoformat()} ({len(evals)} institutions)"
        existing = self._repo.latest_digest_for_subject(subject=subject)
        if existing and existing.status.value == "SENT":
            return {"status": "SKIPPED", "reason": "already_sent", "notification_id": str(existing.id)}

        lines = [
            f"WARNING anomalies digest for {as_of_date.isoformat()}",
            "",
        ]
        for ev in evals:
            lines.append(
                f"- Institution={ev.institution_id} Types={','.join(ev.anomaly_types)} EvalId={ev.id}"
            )
        body = "\n".join(lines)

        # Digest is represented as a NotificationEvent linked to the first evaluation for traceability.
        event = self._repo.create_event(
            evaluation_id=evals[0].id,
            final_anomaly_id=None,
            channel=NotificationChannel.EMAIL,
            severity=Severity.WARNING,
            to_addresses=recipients,
            subject=subject,
            body=body,
        )
        try:
            self._email.send(EmailPayload(to_addresses=recipients, subject=subject, body=body))
            self._repo.mark_sent(notification_id=event.id, sent_at_utc=utc_now())
            return {"status": "SENT", "notification_id": str(event.id), "count": len(evals)}
        except Exception as e:
            self._repo.mark_failed(notification_id=event.id, sent_at_utc=utc_now(), error_text=str(e))
            log.error("warning_digest_send_failed", notification_id=str(event.id), error=str(e))
            return {"status": "FAILED", "notification_id": str(event.id), "error": str(e)}


