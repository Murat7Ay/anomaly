from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import ActorIdDep, InternalAuthDep, get_db
from app.application.profile.profile_service import ProfileService
from app.domain.profile.config import InstitutionProfileConfig
from app.infra.repositories.institution_repo import (
    InstitutionConflictError,
    InstitutionNotFoundError,
    InstitutionRepository,
)
from app.infra.repositories.profile_repo import ProfileConflictError, ProfileNotFoundError

router = APIRouter(prefix="/institutions", tags=["institutions"])


class InstitutionCreateRequest(BaseModel):
    external_code: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=256)
    default_timezone: str | None = Field(default=None, max_length=64)
    default_calendar_id: uuid.UUID | None = None


class InstitutionResponse(BaseModel):
    id: uuid.UUID
    external_code: str
    display_name: str
    active: bool
    default_timezone: str | None
    default_calendar_id: uuid.UUID | None


class ProfileDraftCreateRequest(BaseModel):
    effective_from: date
    config: InstitutionProfileConfig


class ProfileVersionResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    version_num: int
    status: str
    effective_from: date
    effective_to: date | None
    schema_version: int
    config_hash: str
    config_json: dict
    created_by: str
    created_at_utc: str
    approved_at_utc: str | None
    approved_by: str | None
    approval_reason: str | None


class ApproveRequest(BaseModel):
    approval_reason: str | None = Field(default=None, max_length=512)


class ProfileStatsResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    as_of_date: date
    profile_config_version_id: uuid.UUID
    algorithm_version: str
    snapshot_hash: str
    snapshot_json: dict
    data_cutoff_utc: str | None
    created_at_utc: str


@router.post("", response_model=InstitutionResponse, status_code=status.HTTP_201_CREATED, dependencies=[InternalAuthDep])
def create_institution(req: InstitutionCreateRequest, db: Session = Depends(get_db)) -> InstitutionResponse:
    repo = InstitutionRepository(db)
    try:
        inst = repo.create(
            external_code=req.external_code,
            display_name=req.display_name,
            default_timezone=req.default_timezone,
            default_calendar_id=req.default_calendar_id,
        )
    except InstitutionConflictError:
        raise HTTPException(status_code=409, detail="institution_code_conflict")
    return InstitutionResponse(
        id=inst.id,
        external_code=inst.external_code,
        display_name=inst.display_name,
        active=inst.active,
        default_timezone=inst.default_timezone,
        default_calendar_id=inst.default_calendar_id,
    )


@router.get("", response_model=list[InstitutionResponse], dependencies=[InternalAuthDep])
def list_institutions(db: Session = Depends(get_db)) -> list[InstitutionResponse]:
    repo = InstitutionRepository(db)
    insts = repo.list()
    return [
        InstitutionResponse(
            id=i.id,
            external_code=i.external_code,
            display_name=i.display_name,
            active=i.active,
            default_timezone=i.default_timezone,
            default_calendar_id=i.default_calendar_id,
        )
        for i in insts
    ]


@router.get("/{institution_id}", response_model=InstitutionResponse, dependencies=[InternalAuthDep])
def get_institution(institution_id: uuid.UUID, db: Session = Depends(get_db)) -> InstitutionResponse:
    repo = InstitutionRepository(db)
    try:
        inst = repo.get(institution_id)
    except InstitutionNotFoundError:
        raise HTTPException(status_code=404, detail="institution_not_found")
    return InstitutionResponse(
        id=inst.id,
        external_code=inst.external_code,
        display_name=inst.display_name,
        active=inst.active,
        default_timezone=inst.default_timezone,
        default_calendar_id=inst.default_calendar_id,
    )


@router.post(
    "/{institution_id}/profile/draft",
    response_model=ProfileVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[InternalAuthDep],
)
def create_profile_draft(
    institution_id: uuid.UUID,
    req: ProfileDraftCreateRequest,
    actor_id: str = ActorIdDep,
    db: Session = Depends(get_db),
) -> ProfileVersionResponse:
    svc = ProfileService(db)
    try:
        v = svc.create_draft(
            institution_id=institution_id,
            effective_from=req.effective_from,
            created_by=actor_id,
            config=req.config,
        )
    except InstitutionNotFoundError:
        raise HTTPException(status_code=404, detail="institution_not_found")
    except ProfileConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ProfileVersionResponse(
        id=v.id,
        institution_id=v.institution_id,
        version_num=v.version_num,
        status=v.status.value if hasattr(v.status, "value") else str(v.status),
        effective_from=v.effective_from,
        effective_to=v.effective_to,
        schema_version=v.schema_version,
        config_hash=v.config_hash,
        config_json=v.config_json,
        created_by=v.created_by,
        created_at_utc=v.created_at_utc.isoformat(),
        approved_at_utc=v.approved_at_utc.isoformat() if v.approved_at_utc else None,
        approved_by=v.approved_by,
        approval_reason=v.approval_reason,
    )


@router.get(
    "/{institution_id}/profile/versions",
    response_model=list[ProfileVersionResponse],
    dependencies=[InternalAuthDep],
)
def list_profile_versions(institution_id: uuid.UUID, db: Session = Depends(get_db)) -> list[ProfileVersionResponse]:
    svc = ProfileService(db)
    try:
        versions = svc.list_versions(institution_id=institution_id)
    except InstitutionNotFoundError:
        raise HTTPException(status_code=404, detail="institution_not_found")
    return [
        ProfileVersionResponse(
            id=v.id,
            institution_id=v.institution_id,
            version_num=v.version_num,
            status=v.status.value if hasattr(v.status, "value") else str(v.status),
            effective_from=v.effective_from,
            effective_to=v.effective_to,
            schema_version=v.schema_version,
            config_hash=v.config_hash,
            config_json=v.config_json,
            created_by=v.created_by,
            created_at_utc=v.created_at_utc.isoformat(),
            approved_at_utc=v.approved_at_utc.isoformat() if v.approved_at_utc else None,
            approved_by=v.approved_by,
            approval_reason=v.approval_reason,
        )
        for v in versions
    ]


@router.post(
    "/{institution_id}/profile/versions/{version_id}/approve",
    response_model=ProfileVersionResponse,
    dependencies=[InternalAuthDep],
)
def approve_profile_version(
    institution_id: uuid.UUID,
    version_id: uuid.UUID,
    req: ApproveRequest,
    actor_id: str = ActorIdDep,
    db: Session = Depends(get_db),
) -> ProfileVersionResponse:
    svc = ProfileService(db)
    try:
        v = svc.approve_version(
            institution_id=institution_id,
            version_id=version_id,
            approved_by=actor_id,
            approval_reason=req.approval_reason,
        )
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="profile_version_not_found")
    except ProfileConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return ProfileVersionResponse(
        id=v.id,
        institution_id=v.institution_id,
        version_num=v.version_num,
        status=v.status.value if hasattr(v.status, "value") else str(v.status),
        effective_from=v.effective_from,
        effective_to=v.effective_to,
        schema_version=v.schema_version,
        config_hash=v.config_hash,
        config_json=v.config_json,
        created_by=v.created_by,
        created_at_utc=v.created_at_utc.isoformat(),
        approved_at_utc=v.approved_at_utc.isoformat() if v.approved_at_utc else None,
        approved_by=v.approved_by,
        approval_reason=v.approval_reason,
    )


@router.get(
    "/{institution_id}/profile/effective",
    response_model=ProfileVersionResponse,
    dependencies=[InternalAuthDep],
)
def get_effective_profile(
    institution_id: uuid.UUID,
    as_of: date,
    db: Session = Depends(get_db),
) -> ProfileVersionResponse:
    svc = ProfileService(db)
    try:
        v = svc.get_effective(institution_id=institution_id, as_of_date=as_of)
    except InstitutionNotFoundError:
        raise HTTPException(status_code=404, detail="institution_not_found")
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="effective_profile_not_found")
    return ProfileVersionResponse(
        id=v.id,
        institution_id=v.institution_id,
        version_num=v.version_num,
        status=v.status.value if hasattr(v.status, "value") else str(v.status),
        effective_from=v.effective_from,
        effective_to=v.effective_to,
        schema_version=v.schema_version,
        config_hash=v.config_hash,
        config_json=v.config_json,
        created_by=v.created_by,
        created_at_utc=v.created_at_utc.isoformat(),
        approved_at_utc=v.approved_at_utc.isoformat() if v.approved_at_utc else None,
        approved_by=v.approved_by,
        approval_reason=v.approval_reason,
    )


@router.get(
    "/{institution_id}/profile/stats",
    response_model=ProfileStatsResponse,
    dependencies=[InternalAuthDep],
)
def get_profile_stats_snapshot(
    institution_id: uuid.UUID,
    as_of: date,
    profile_version_id: uuid.UUID | None = None,
    db: Session = Depends(get_db),
) -> ProfileStatsResponse:
    svc = ProfileService(db)
    try:
        s = svc.get_or_compute_stats_snapshot(
            institution_id=institution_id, as_of_date=as_of, profile_version_id=profile_version_id
        )
    except InstitutionNotFoundError:
        raise HTTPException(status_code=404, detail="institution_not_found")
    except ProfileNotFoundError:
        raise HTTPException(status_code=404, detail="profile_version_not_found")
    except ProfileConflictError as e:
        # e.g. stats_not_enabled_yet
        raise HTTPException(status_code=409, detail=str(e))
    return ProfileStatsResponse(
        id=s.id,
        institution_id=s.institution_id,
        as_of_date=s.as_of_date,
        profile_config_version_id=s.profile_config_version_id,
        algorithm_version=s.algorithm_version,
        snapshot_hash=s.snapshot_hash,
        snapshot_json=s.snapshot_json,
        data_cutoff_utc=s.data_cutoff_utc.isoformat() if s.data_cutoff_utc else None,
        created_at_utc=s.created_at_utc.isoformat(),
    )


