from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import VersionStatus
from app.domain.profile.config import InstitutionProfileConfig
from app.infra.db.models.profile import InstitutionProfileConfigVersion, InstitutionProfileStatsSnapshot


class ProfileConflictError(Exception):
    pass


class ProfileNotFoundError(Exception):
    pass


class ProfileRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def _next_version_num(self, institution_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(InstitutionProfileConfigVersion.version_num), 0)).where(
            InstitutionProfileConfigVersion.institution_id == institution_id
        )
        return int(self._db.execute(stmt).scalar_one()) + 1

    def create_draft(
        self,
        *,
        institution_id: uuid.UUID,
        effective_from: date,
        created_by: str,
        config: InstitutionProfileConfig,
    ) -> InstitutionProfileConfigVersion:
        version_num = self._next_version_num(institution_id)
        row = InstitutionProfileConfigVersion(
            institution_id=institution_id,
            version_num=version_num,
            status=VersionStatus.DRAFT,
            effective_from=effective_from,
            effective_to=None,
            schema_version=1,
            config_hash=config.config_hash(),
            config_json=config.canonical_json(),
            created_by=created_by,
        )
        self._db.add(row)
        try:
            self._db.commit()
        except IntegrityError as e:
            self._db.rollback()
            raise ProfileConflictError("profile_version_conflict") from e
        self._db.refresh(row)
        return row

    def list_versions(self, institution_id: uuid.UUID) -> list[InstitutionProfileConfigVersion]:
        stmt = (
            select(InstitutionProfileConfigVersion)
            .where(InstitutionProfileConfigVersion.institution_id == institution_id)
            .order_by(InstitutionProfileConfigVersion.version_num.desc())
        )
        return list(self._db.execute(stmt).scalars().all())

    def get_version(self, version_id: uuid.UUID) -> InstitutionProfileConfigVersion:
        row = self._db.get(InstitutionProfileConfigVersion, version_id)
        if not row:
            raise ProfileNotFoundError("profile_version_not_found")
        return row

    def approve_version(
        self,
        *,
        version_id: uuid.UUID,
        approved_by: str,
        approval_reason: str | None,
        approved_at_utc: datetime,
    ) -> InstitutionProfileConfigVersion:
        row = self.get_version(version_id)
        if row.status != VersionStatus.DRAFT:
            raise ProfileConflictError("profile_version_not_draft")
        row.status = VersionStatus.APPROVED
        row.approved_by = approved_by
        row.approval_reason = approval_reason
        row.approved_at_utc = approved_at_utc
        self._db.add(row)
        self._db.commit()
        self._db.refresh(row)
        return row

    def effective_version(self, *, institution_id: uuid.UUID, as_of_date: date) -> InstitutionProfileConfigVersion:
        stmt = (
            select(InstitutionProfileConfigVersion)
            .where(
                and_(
                    InstitutionProfileConfigVersion.institution_id == institution_id,
                    InstitutionProfileConfigVersion.status == VersionStatus.APPROVED,
                    InstitutionProfileConfigVersion.effective_from <= as_of_date,
                    sa.or_(
                        InstitutionProfileConfigVersion.effective_to.is_(None),
                        InstitutionProfileConfigVersion.effective_to >= as_of_date,
                    ),
                )
            )
            .order_by(InstitutionProfileConfigVersion.version_num.desc())
            .limit(1)
        )
        row = self._db.execute(stmt).scalars().first()
        if not row:
            raise ProfileNotFoundError("effective_profile_not_found")
        return row

    def effective_version_as_of(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        approved_cutoff_utc: datetime,
    ) -> InstitutionProfileConfigVersion:
        stmt = (
            select(InstitutionProfileConfigVersion)
            .where(
                and_(
                    InstitutionProfileConfigVersion.institution_id == institution_id,
                    InstitutionProfileConfigVersion.status == VersionStatus.APPROVED,
                    InstitutionProfileConfigVersion.approved_at_utc.is_not(None),
                    InstitutionProfileConfigVersion.approved_at_utc <= approved_cutoff_utc,
                    InstitutionProfileConfigVersion.effective_from <= as_of_date,
                    sa.or_(
                        InstitutionProfileConfigVersion.effective_to.is_(None),
                        InstitutionProfileConfigVersion.effective_to >= as_of_date,
                    ),
                )
            )
            .order_by(InstitutionProfileConfigVersion.version_num.desc())
            .limit(1)
        )
        row = self._db.execute(stmt).scalars().first()
        if not row:
            raise ProfileNotFoundError("effective_profile_not_found")
        return row


class ProfileStatsRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def get_snapshot(
        self, *, institution_id: uuid.UUID, as_of_date: date, profile_config_version_id: uuid.UUID
    ) -> InstitutionProfileStatsSnapshot | None:
        stmt = select(InstitutionProfileStatsSnapshot).where(
            and_(
                InstitutionProfileStatsSnapshot.institution_id == institution_id,
                InstitutionProfileStatsSnapshot.as_of_date == as_of_date,
                InstitutionProfileStatsSnapshot.profile_config_version_id == profile_config_version_id,
            )
        )
        return self._db.execute(stmt).scalars().first()

    def upsert_snapshot(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        profile_config_version_id: uuid.UUID,
        snapshot_hash: str,
        snapshot_json: dict,
        algorithm_version: str,
        data_cutoff_utc: datetime | None,
    ) -> InstitutionProfileStatsSnapshot:
        existing = self.get_snapshot(
            institution_id=institution_id,
            as_of_date=as_of_date,
            profile_config_version_id=profile_config_version_id,
        )
        if existing:
            return existing
        row = InstitutionProfileStatsSnapshot(
            institution_id=institution_id,
            as_of_date=as_of_date,
            profile_config_version_id=profile_config_version_id,
            snapshot_hash=snapshot_hash,
            snapshot_json=snapshot_json,
            algorithm_version=algorithm_version,
            data_cutoff_utc=data_cutoff_utc,
        )
        self._db.add(row)
        try:
            self._db.commit()
        except IntegrityError:
            self._db.rollback()
            # Another worker may have inserted concurrently; return the winner.
            existing2 = self.get_snapshot(
                institution_id=institution_id,
                as_of_date=as_of_date,
                profile_config_version_id=profile_config_version_id,
            )
            if existing2:
                return existing2
            raise
        self._db.refresh(row)
        return row


