from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.infra.db.models.load import LoadBatch


class LoadRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_by_local_date_range(
        self,
        *,
        institution_id: uuid.UUID,
        start_date: date,
        end_date_exclusive: date,
    ) -> list[LoadBatch]:
        stmt = (
            select(LoadBatch)
            .where(
                and_(
                    LoadBatch.institution_id == institution_id,
                    LoadBatch.institution_local_date >= start_date,
                    LoadBatch.institution_local_date < end_date_exclusive,
                )
            )
            .order_by(LoadBatch.institution_local_date.asc(), LoadBatch.received_at_utc.asc())
        )
        return list(self._db.execute(stmt).scalars().all())


