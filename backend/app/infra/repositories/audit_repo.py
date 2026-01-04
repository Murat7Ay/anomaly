from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.infra.db.models.audit import AuditEvent


class AuditRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        *,
        actor_type: str,
        actor_id: str,
        action: str,
        object_type: str,
        object_id: str,
        before_hash: str | None,
        after_hash: str | None,
        request_id: str | None,
        message: str | None,
        metadata_json: dict,
        created_at_utc: datetime | None = None,
    ) -> AuditEvent:
        row = AuditEvent(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            object_type=object_type,
            object_id=object_id,
            before_hash=before_hash,
            after_hash=after_hash,
            request_id=request_id,
            message=message,
            metadata_json=metadata_json,
        )
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row


