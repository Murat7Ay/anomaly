from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infra.db.models.institution import Institution


class InstitutionConflictError(Exception):
    pass


class InstitutionNotFoundError(Exception):
    pass


class InstitutionRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(
        self,
        *,
        external_code: str,
        display_name: str,
        default_timezone: str | None,
        default_calendar_id: uuid.UUID | None,
    ) -> Institution:
        inst = Institution(
            external_code=external_code,
            display_name=display_name,
            default_timezone=default_timezone,
            default_calendar_id=default_calendar_id,
        )
        self._db.add(inst)
        try:
            self._db.commit()
        except IntegrityError as e:
            self._db.rollback()
            raise InstitutionConflictError("institution_code_conflict") from e
        self._db.refresh(inst)
        return inst

    def list(self) -> list[Institution]:
        rows = self._db.execute(select(Institution).order_by(Institution.external_code)).scalars().all()
        return list(rows)

    def list_active(self) -> list[Institution]:
        rows = (
            self._db.execute(
                select(Institution).where(Institution.active.is_(True)).order_by(Institution.external_code)
            )
            .scalars()
            .all()
        )
        return list(rows)

    def get(self, institution_id: uuid.UUID) -> Institution:
        inst = self._db.get(Institution, institution_id)
        if not inst:
            raise InstitutionNotFoundError("institution_not_found")
        return inst


