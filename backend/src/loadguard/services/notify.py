"""Page humans only when it matters: P1/P2, still open, not part of a systemic incident, not suppressed."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy.orm import Session

from loadguard.core import clock
from loadguard.core.config import get_settings
from loadguard.core.logging import get_logger
from loadguard.db.models import Incident, Notification
from loadguard.services.incidents import describe_impact

log = get_logger(__name__)


def notify_incident(s: Session, incident_id: uuid.UUID) -> str:
    inc = s.get(Incident, incident_id)
    if inc is None:
        return "missing"
    if inc.status == "RESOLVED":
        return "skipped:resolved"
    if inc.parent_id is not None:
        return "skipped:grouped_in_systemic"
    settings = get_settings()
    url = f"{settings.public_base_url}/incidents/{inc.id}"
    impact = describe_impact(inc)
    text = (
        f"[{inc.priority}] #{inc.number} {inc.title}" + (f" — Etki: {impact}" if impact else "") + f"\n{url}"
    )
    payload = {"text": text, "incident": {"id": str(inc.id), "number": inc.number, "priority": inc.priority}}
    channel, target, status, error = "LOG", "stdout", "SENT", None
    if settings.notify_webhook_url:
        channel, target = "WEBHOOK", settings.notify_webhook_url
        try:
            httpx.post(settings.notify_webhook_url, json=payload, timeout=10).raise_for_status()
        except httpx.HTTPError as e:
            status, error = "FAILED", str(e)
    else:
        log.warning("incident_notification", text=text)
    s.add(
        Notification(
            incident_id=inc.id,
            channel=channel,
            target=target,
            status=status,
            at=clock.now(),
            error=error,
            payload=payload,
        )
    )
    if status == "FAILED":
        raise RuntimeError(f"notification failed: {error}")  # job retries with backoff
    return "sent"
