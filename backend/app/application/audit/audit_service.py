from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from app.infra.repositories.audit_repo import AuditRepository


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class AuditService:
    """
    Writes immutable audit events for regulated operations (profile approvals, DSL changes, etc).
    """

    def __init__(self, db: Session) -> None:
        self._repo = AuditRepository(db)

    def record(
        self,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        object_type: str,
        object_id: str,
        before_hash: str | None,
        after_hash: str | None,
        message: str | None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        ctx = structlog.contextvars.get_contextvars()
        request_id = ctx.get("request_id")
        self._repo.create(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            before_hash=before_hash,
            after_hash=after_hash,
            request_id=request_id,
            message=message,
            metadata_json=metadata or {},
            created_at_utc=utc_now(),
        )


