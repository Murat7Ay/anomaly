from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import VersionStatus
from app.infra.db.models.dsl import DslRuleSetVersion


class DslConflictError(Exception):
    pass


class DslNotFoundError(Exception):
    pass


class DslRuleSetRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _next_version_num(self, institution_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(DslRuleSetVersion.version_num), 0)).where(
            DslRuleSetVersion.institution_id == institution_id
        )
        return int(self._db.execute(stmt).scalar_one()) + 1

    def create_draft(
        self,
        *,
        institution_id: uuid.UUID,
        effective_from: date,
        created_by: str,
        rules_hash: str,
        rules_json: dict,
        compiled_hash: str | None,
        compiled_json: dict | None,
        validation_report_json: dict | None,
    ) -> DslRuleSetVersion:
        version_num = self._next_version_num(institution_id)
        row = DslRuleSetVersion(
            institution_id=institution_id,
            version_num=version_num,
            status=VersionStatus.DRAFT,
            effective_from=effective_from,
            effective_to=None,
            schema_version=1,
            rules_hash=rules_hash,
            rules_json=rules_json,
            compiled_hash=compiled_hash,
            compiled_json=compiled_json,
            validation_report_json=validation_report_json,
            created_by=created_by,
        )
        self._db.add(row)
        try:
            self._db.commit()
        except IntegrityError as e:
            self._db.rollback()
            raise DslConflictError("dsl_version_conflict") from e
        self._db.refresh(row)
        return row

    def list_versions(self, institution_id: uuid.UUID) -> list[DslRuleSetVersion]:
        stmt = (
            select(DslRuleSetVersion)
            .where(DslRuleSetVersion.institution_id == institution_id)
            .order_by(DslRuleSetVersion.version_num.desc())
        )
        return list(self._db.execute(stmt).scalars().all())

    def get_version(self, version_id: uuid.UUID) -> DslRuleSetVersion:
        row = self._db.get(DslRuleSetVersion, version_id)
        if not row:
            raise DslNotFoundError("dsl_version_not_found")
        return row

    def update_compiled_artifacts(
        self,
        *,
        version_id: uuid.UUID,
        compiled_hash: str,
        compiled_json: dict,
        validation_report_json: dict,
    ) -> DslRuleSetVersion:
        row = self.get_version(version_id)
        if row.status != VersionStatus.DRAFT:
            raise DslConflictError("dsl_version_not_draft")
        row.compiled_hash = compiled_hash
        row.compiled_json = compiled_json
        row.validation_report_json = validation_report_json
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def approve_version(
        self,
        *,
        version_id: uuid.UUID,
        approved_by: str,
        approval_reason: str | None,
        approved_at_utc: datetime,
    ) -> DslRuleSetVersion:
        row = self.get_version(version_id)
        if row.status != VersionStatus.DRAFT:
            raise DslConflictError("dsl_version_not_draft")
        if row.compiled_hash is None or row.compiled_json is None or row.validation_report_json is None:
            raise DslConflictError("dsl_not_validated")
        row.status = VersionStatus.APPROVED
        row.approved_by = approved_by
        row.approval_reason = approval_reason
        row.approved_at_utc = approved_at_utc
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def effective_version(self, *, institution_id: uuid.UUID, as_of_date: date) -> DslRuleSetVersion:
        import sqlalchemy as sa

        stmt = (
            select(DslRuleSetVersion)
            .where(
                and_(
                    DslRuleSetVersion.institution_id == institution_id,
                    DslRuleSetVersion.status == VersionStatus.APPROVED,
                    DslRuleSetVersion.effective_from <= as_of_date,
                    sa.or_(
                        DslRuleSetVersion.effective_to.is_(None),
                        DslRuleSetVersion.effective_to >= as_of_date,
                    ),
                )
            )
            .order_by(DslRuleSetVersion.version_num.desc())
            .limit(1)
        )
        row = self._db.execute(stmt).scalars().first()
        if not row:
            raise DslNotFoundError("effective_dsl_not_found")
        return row

    def effective_version_as_of(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        approved_cutoff_utc: datetime,
    ) -> DslRuleSetVersion:
        import sqlalchemy as sa

        stmt = (
            select(DslRuleSetVersion)
            .where(
                and_(
                    DslRuleSetVersion.institution_id == institution_id,
                    DslRuleSetVersion.status == VersionStatus.APPROVED,
                    DslRuleSetVersion.approved_at_utc.is_not(None),
                    DslRuleSetVersion.approved_at_utc <= approved_cutoff_utc,
                    DslRuleSetVersion.effective_from <= as_of_date,
                    sa.or_(
                        DslRuleSetVersion.effective_to.is_(None),
                        DslRuleSetVersion.effective_to >= as_of_date,
                    ),
                )
            )
            .order_by(DslRuleSetVersion.version_num.desc())
            .limit(1)
        )
        row = self._db.execute(stmt).scalars().first()
        if not row:
            raise DslNotFoundError("effective_dsl_not_found")
        return row


