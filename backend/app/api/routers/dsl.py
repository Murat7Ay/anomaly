from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import ActorIdDep, InternalAuthDep, get_db
from app.application.dsl.dsl_service import DslService
from app.infra.repositories.dsl_repo import DslConflictError, DslNotFoundError
from app.infra.repositories.institution_repo import InstitutionNotFoundError

router = APIRouter(prefix="/institutions/{institution_id}/dsl", tags=["dsl"])


class DslDraftCreateRequest(BaseModel):
    effective_from: date
    rules_json: dict = Field(default_factory=dict)


class ApproveRequest(BaseModel):
    approval_reason: str | None = Field(default=None, max_length=512)


class DslRuleSetVersionResponse(BaseModel):
    id: uuid.UUID
    institution_id: uuid.UUID
    version_num: int
    status: str
    effective_from: date
    effective_to: date | None
    schema_version: int
    rules_hash: str
    rules_json: dict
    compiled_hash: str | None
    compiled_json: dict | None
    validation_report_json: dict | None
    created_by: str
    created_at_utc: str
    approved_at_utc: str | None
    approved_by: str | None
    approval_reason: str | None


class DslSandboxRequest(BaseModel):
    rules_json: dict
    test_cases: list[dict]


@router.post(
    "/draft",
    response_model=DslRuleSetVersionResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[InternalAuthDep],
)
def create_dsl_draft(
    institution_id: uuid.UUID,
    req: DslDraftCreateRequest,
    actor_id: str = ActorIdDep,
    db: Session = Depends(get_db),
) -> DslRuleSetVersionResponse:
    svc = DslService(db)
    try:
        row = svc.create_draft(
            institution_id=institution_id,
            effective_from=req.effective_from,
            created_by=actor_id,
            rules_json=req.rules_json,
        )
    except InstitutionNotFoundError:
        raise HTTPException(status_code=404, detail="institution_not_found")
    except DslConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_resp(row)


@router.get("/versions", response_model=list[DslRuleSetVersionResponse], dependencies=[InternalAuthDep])
def list_dsl_versions(institution_id: uuid.UUID, db: Session = Depends(get_db)) -> list[DslRuleSetVersionResponse]:
    svc = DslService(db)
    try:
        rows = svc.list_versions(institution_id=institution_id)
    except InstitutionNotFoundError:
        raise HTTPException(status_code=404, detail="institution_not_found")
    return [_to_resp(r) for r in rows]


@router.post(
    "/versions/{version_id}/validate",
    response_model=DslRuleSetVersionResponse,
    dependencies=[InternalAuthDep],
)
def validate_dsl_version(
    institution_id: uuid.UUID,
    version_id: uuid.UUID,
    actor_id: str = ActorIdDep,
    db: Session = Depends(get_db),
) -> DslRuleSetVersionResponse:
    svc = DslService(db)
    try:
        row = svc.validate_existing_draft(institution_id=institution_id, version_id=version_id, actor_id=actor_id)
    except DslNotFoundError:
        raise HTTPException(status_code=404, detail="dsl_version_not_found")
    except DslConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_resp(row)


@router.post(
    "/versions/{version_id}/approve",
    response_model=DslRuleSetVersionResponse,
    dependencies=[InternalAuthDep],
)
def approve_dsl_version(
    institution_id: uuid.UUID,
    version_id: uuid.UUID,
    req: ApproveRequest,
    actor_id: str = ActorIdDep,
    db: Session = Depends(get_db),
) -> DslRuleSetVersionResponse:
    svc = DslService(db)
    try:
        row = svc.approve_version(
            institution_id=institution_id,
            version_id=version_id,
            approved_by=actor_id,
            approval_reason=req.approval_reason,
        )
    except DslNotFoundError:
        raise HTTPException(status_code=404, detail="dsl_version_not_found")
    except DslConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return _to_resp(row)


@router.get("/effective", response_model=DslRuleSetVersionResponse, dependencies=[InternalAuthDep])
def get_effective_dsl(
    institution_id: uuid.UUID,
    as_of: date,
    db: Session = Depends(get_db),
) -> DslRuleSetVersionResponse:
    svc = DslService(db)
    try:
        row = svc.get_effective(institution_id=institution_id, as_of_date=as_of)
    except InstitutionNotFoundError:
        raise HTTPException(status_code=404, detail="institution_not_found")
    except DslNotFoundError:
        raise HTTPException(status_code=404, detail="effective_dsl_not_found")
    return _to_resp(row)


@router.post("/sandbox", dependencies=[InternalAuthDep])
def sandbox_dsl(
    institution_id: uuid.UUID,
    req: DslSandboxRequest,
    db: Session = Depends(get_db),
) -> dict:
    svc = DslService(db)
    return svc.sandbox(institution_id=institution_id, rules_json=req.rules_json, test_cases=req.test_cases)


def _to_resp(row) -> DslRuleSetVersionResponse:
    return DslRuleSetVersionResponse(
        id=row.id,
        institution_id=row.institution_id,
        version_num=row.version_num,
        status=row.status.value if hasattr(row.status, "value") else str(row.status),
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        schema_version=row.schema_version,
        rules_hash=row.rules_hash,
        rules_json=row.rules_json,
        compiled_hash=row.compiled_hash,
        compiled_json=row.compiled_json,
        validation_report_json=row.validation_report_json,
        created_by=row.created_by,
        created_at_utc=row.created_at_utc.isoformat(),
        approved_at_utc=row.approved_at_utc.isoformat() if row.approved_at_utc else None,
        approved_by=row.approved_by,
        approval_reason=row.approval_reason,
    )


