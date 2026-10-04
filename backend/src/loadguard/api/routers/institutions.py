from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import select

from loadguard.ai.contract_assist import propose
from loadguard.api.deps import DB, CurrentUser, require_roles
from loadguard.api.schemas import AssistIn, BacktestIn, DecisionIn, DraftIn, InstitutionIn, InstitutionPatch
from loadguard.core.errors import Conflict, NotFound
from loadguard.db.models import ContractVersion, Institution
from loadguard.domain.contract import ContractSpec
from loadguard.services import analytics
from loadguard.services import contracts as svc
from loadguard.services.common import audit

router = APIRouter(tags=["institutions & contracts"])
ADMIN = require_roles("ADMIN")


@router.get("/institutions")
def list_institutions(s: DB, _: CurrentUser) -> list[dict[str, Any]]:
    return analytics.institutions_health(s)


@router.post("/institutions", status_code=201, dependencies=[ADMIN])
def create_institution(body: InstitutionIn, s: DB, user: CurrentUser) -> dict[str, Any]:
    if s.scalars(select(Institution).where(Institution.code == body.code)).first():
        raise Conflict("Bu kurum kodu zaten kayıtlı")
    inst = Institution(**body.model_dump())
    s.add(inst)
    s.flush()
    audit(s, user.username, "institution.created", "institution", inst.id, code=body.code)
    return {"id": str(inst.id)}


def _inst(s: DB, institution_id: uuid.UUID) -> Institution:
    inst = s.get(Institution, institution_id)
    if inst is None:
        raise NotFound("Kurum bulunamadı")
    return inst


@router.get("/institutions/{institution_id}")
def get_institution(institution_id: uuid.UUID, s: DB, _: CurrentUser) -> dict[str, Any]:
    inst = _inst(s, institution_id)
    eff = svc.effective_contract(s, inst.id, analytics.today())
    return {
        "id": str(inst.id),
        "code": inst.code,
        "name": inst.name,
        "sector": inst.sector,
        "tier": inst.tier,
        "active": inst.active,
        "contact_email": inst.contact_email,
        "notes": inst.notes,
        "contract": analytics.contract_view(eff[0]) if eff else None,
    }


@router.patch("/institutions/{institution_id}", dependencies=[ADMIN])
def patch_institution(
    institution_id: uuid.UUID, body: InstitutionPatch, s: DB, user: CurrentUser
) -> dict[str, Any]:
    inst = _inst(s, institution_id)
    changes = body.model_dump(exclude_unset=True)
    for k, v in changes.items():
        setattr(inst, k, v)
    audit(s, user.username, "institution.updated", "institution", inst.id, **changes)
    return {"ok": True}


@router.get("/institutions/{institution_id}/series")
def series(
    institution_id: uuid.UUID,
    s: DB,
    _: CurrentUser,
    metric: str = Query(
        default="record_count", pattern="^(record_count|total_amount|customer_count|avg_amount)$"
    ),
    days: int = Query(default=120, ge=7, le=730),
) -> list[dict[str, Any]]:
    _inst(s, institution_id)
    return analytics.institution_series(s, institution_id, metric, days)


@router.get("/institutions/{institution_id}/contracts")
def list_contracts(institution_id: uuid.UUID, s: DB, _: CurrentUser) -> list[dict[str, Any]]:
    rows = s.scalars(
        select(ContractVersion)
        .where(ContractVersion.institution_id == institution_id)
        .order_by(ContractVersion.version.desc())
    ).all()
    return [analytics.contract_view(cv) for cv in rows]


@router.post("/institutions/{institution_id}/contracts", status_code=201)
def create_draft(institution_id: uuid.UUID, body: DraftIn, s: DB, user: CurrentUser) -> dict[str, Any]:
    cv = svc.create_draft(
        s,
        actor=user.username,
        institution_id=institution_id,
        spec=body.spec,
        effective_from=body.effective_from,
        change_note=body.change_note,
        origin=body.origin,
    )
    return analytics.contract_view(cv)


@router.put("/contracts/{version_id}")
def update_draft(version_id: uuid.UUID, body: DraftIn, s: DB, user: CurrentUser) -> dict[str, Any]:
    cv = svc.update_draft(
        s,
        actor=user.username,
        version_id=version_id,
        spec=body.spec,
        effective_from=body.effective_from,
        change_note=body.change_note,
    )
    return analytics.contract_view(cv)


@router.post("/contracts/{version_id}/submit")
def submit(version_id: uuid.UUID, s: DB, user: CurrentUser) -> dict[str, Any]:
    return analytics.contract_view(svc.submit(s, actor=user.username, version_id=version_id))


@router.post("/contracts/{version_id}/approve")
def approve(version_id: uuid.UUID, body: DecisionIn, s: DB, user: CurrentUser) -> dict[str, Any]:
    cv = svc.decide(
        s, actor=user.username, role=user.role, version_id=version_id, approve=True, note=body.note
    )
    return analytics.contract_view(cv)


@router.post("/contracts/{version_id}/reject")
def reject(version_id: uuid.UUID, body: DecisionIn, s: DB, user: CurrentUser) -> dict[str, Any]:
    cv = svc.decide(
        s, actor=user.username, role=user.role, version_id=version_id, approve=False, note=body.note
    )
    return analytics.contract_view(cv)


@router.post("/contracts/{version_id}/withdraw")
def withdraw(version_id: uuid.UUID, s: DB, user: CurrentUser) -> dict[str, Any]:
    return analytics.contract_view(svc.withdraw(s, actor=user.username, version_id=version_id))


@router.get("/approvals")
def approvals(s: DB, _: CurrentUser) -> list[dict[str, Any]]:
    rows = s.execute(
        select(ContractVersion, Institution.name)
        .join(Institution, Institution.id == ContractVersion.institution_id)
        .where(ContractVersion.status == "PENDING_APPROVAL")
        .order_by(ContractVersion.submitted_at)
    ).all()
    out = []
    for cv, name in rows:
        current = svc.effective_contract(s, cv.institution_id, analytics.today())
        out.append(
            {
                **analytics.contract_view(cv),
                "institution": name,
                "current": analytics.contract_view(current[0]) if current else None,
            }
        )
    return out


@router.post("/institutions/{institution_id}/backtest")
def backtest(institution_id: uuid.UUID, body: BacktestIn, s: DB, _: CurrentUser) -> dict[str, Any]:
    _inst(s, institution_id)
    return svc.backtest(s, institution_id, body.spec, days=body.days)


@router.get("/institutions/{institution_id}/suggestions")
def suggestions(institution_id: uuid.UUID, s: DB, _: CurrentUser) -> dict[str, Any]:
    _inst(s, institution_id)
    inferred = svc.infer_from_history(s, institution_id)
    return {
        "tuning": [sg.to_dict() for sg in svc.tuning_suggestions(s, institution_id)],
        "inferred": {
            "spec": inferred.spec.canonical() if inferred.spec else None,
            "confidence": inferred.confidence,
            "rationale": inferred.rationale,
        },
    }


@router.post("/institutions/{institution_id}/assist")
def assist(institution_id: uuid.UUID, body: AssistIn, s: DB, user: CurrentUser) -> dict[str, Any]:
    _inst(s, institution_id)
    base: ContractSpec | None = body.base_spec
    if base is None:
        eff = svc.effective_contract(s, institution_id, analytics.today())
        if eff is None:
            raise NotFound("Kurumun aktif sözleşmesi yok; önce bir taslak oluşturun")
        base = eff[1]
    return propose(
        s, actor=user.username, institution_id=institution_id, base=base, instruction=body.instruction
    )
