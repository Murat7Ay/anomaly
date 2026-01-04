from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.application.calendar_service import CalendarService
from app.application.profile.profile_stats_builder import ProfileStatsBuilder
from app.application.audit.audit_service import AuditService
from app.domain.profile.config import InstitutionProfileConfig
from app.infra.repositories.calendar_repo import CalendarRepository
from app.infra.repositories.institution_repo import InstitutionNotFoundError, InstitutionRepository
from app.infra.repositories.load_repo import LoadRepository
from app.infra.repositories.profile_repo import (
    ProfileConflictError,
    ProfileNotFoundError,
    ProfileRepository,
    ProfileStatsRepository,
)
from dateutil.relativedelta import relativedelta


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ProfileService:
    def __init__(self, db: Session) -> None:
        self._db = db
        self._inst_repo = InstitutionRepository(db)
        self._profile_repo = ProfileRepository(db)
        self._stats_repo = ProfileStatsRepository(db)
        self._load_repo = LoadRepository(db)
        self._calendar_service = CalendarService(CalendarRepository(db))
        self._stats_builder = ProfileStatsBuilder(calendar_service=self._calendar_service)
        self._audit = AuditService(db)

    def create_draft(
        self,
        *,
        institution_id: uuid.UUID,
        effective_from: date,
        created_by: str,
        config: InstitutionProfileConfig,
    ):
        # Ensure institution exists
        self._inst_repo.get(institution_id)
        row = self._profile_repo.create_draft(
            institution_id=institution_id,
            effective_from=effective_from,
            created_by=created_by,
            config=config,
        )
        self._audit.record(
            actor_type="USER",
            actor_id=created_by,
            action="PROFILE_DRAFT_CREATED",
            object_type="institution_profile_config_version",
            object_id=str(row.id),
            before_hash=None,
            after_hash=row.config_hash,
            message=None,
            metadata={"institution_id": str(institution_id), "effective_from": effective_from.isoformat()},
        )
        return row

    def approve_version(
        self,
        *,
        institution_id: uuid.UUID,
        version_id: uuid.UUID,
        approved_by: str,
        approval_reason: str | None,
    ):
        row = self._profile_repo.get_version(version_id)
        if row.institution_id != institution_id:
            raise ProfileNotFoundError("profile_version_not_found")
        before_hash = row.config_hash
        out = self._profile_repo.approve_version(
            version_id=version_id,
            approved_by=approved_by,
            approval_reason=approval_reason,
            approved_at_utc=utc_now(),
        )
        self._audit.record(
            actor_type="USER",
            actor_id=approved_by,
            action="PROFILE_APPROVED",
            object_type="institution_profile_config_version",
            object_id=str(out.id),
            before_hash=before_hash,
            after_hash=out.config_hash,
            message=approval_reason,
            metadata={"institution_id": str(institution_id), "version_num": out.version_num},
        )
        return out

    def list_versions(self, *, institution_id: uuid.UUID):
        self._inst_repo.get(institution_id)
        return self._profile_repo.list_versions(institution_id)

    def get_effective(self, *, institution_id: uuid.UUID, as_of_date: date):
        self._inst_repo.get(institution_id)
        return self._profile_repo.effective_version(institution_id=institution_id, as_of_date=as_of_date)

    def get_version(self, *, institution_id: uuid.UUID, version_id: uuid.UUID):
        row = self._profile_repo.get_version(version_id)
        if row.institution_id != institution_id:
            raise ProfileNotFoundError("profile_version_not_found")
        return row

    def get_or_compute_stats_snapshot(
        self,
        *,
        institution_id: uuid.UUID,
        as_of_date: date,
        profile_version_id: uuid.UUID | None = None,
    ):
        self._inst_repo.get(institution_id)

        if profile_version_id is None:
            profile_version = self.get_effective(institution_id=institution_id, as_of_date=as_of_date)
        else:
            profile_version = self.get_version(institution_id=institution_id, version_id=profile_version_id)

        profile = InstitutionProfileConfig.model_validate(profile_version.config_json)

        # Strict maturity gating: do not compute snapshots before the profile says stats is enabled.
        stats_enable_date = profile.maturity_policy.first_seen_date + timedelta(
            days=profile.maturity_policy.stats_enabled_after_days
        )
        if as_of_date < stats_enable_date:
            raise ProfileConflictError("stats_not_enabled_yet")

        existing = self._stats_repo.get_snapshot(
            institution_id=institution_id,
            as_of_date=as_of_date,
            profile_config_version_id=profile_version.id,
        )
        if existing:
            return existing

        # Load up to 12 months of history (exclusive of as_of_date)
        history_start = as_of_date - relativedelta(months=12)
        loads = self._load_repo.list_by_local_date_range(
            institution_id=institution_id,
            start_date=history_start,
            end_date_exclusive=as_of_date,
        )
        snapshot_hash, snapshot_json, computed_at_utc = self._stats_builder.build_snapshot(
            institution_id=institution_id,
            profile=profile,
            as_of_date=as_of_date,
            load_batches=loads,
        )
        return self._stats_repo.upsert_snapshot(
            institution_id=institution_id,
            as_of_date=as_of_date,
            profile_config_version_id=profile_version.id,
            snapshot_hash=snapshot_hash,
            snapshot_json=snapshot_json,
            algorithm_version=self._stats_builder.ALGORITHM_VERSION,
            data_cutoff_utc=computed_at_utc,
        )


