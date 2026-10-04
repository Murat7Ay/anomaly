from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text

from loadguard.api.deps import DB, CurrentUser, ingest_auth, issue_token, require_roles
from loadguard.api.schemas import LoadIn, LoginIn, SuppressionIn, iso
from loadguard.core import clock
from loadguard.core.config import get_settings
from loadguard.core.errors import Forbidden, Invalid, NotFound
from loadguard.db.models import AuditLog, Institution, Suppression, User
from loadguard.domain.contract import ContractSpec
from loadguard.services import analytics, pipeline
from loadguard.services.common import audit
from loadguard.services.incidents import RESOLUTIONS

router = APIRouter()


@router.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", tags=["meta"])
def ready(s: DB) -> dict[str, str]:
    s.execute(text("select 1"))
    return {"status": "ready"}


@router.get("/meta", tags=["meta"])
def meta(_: CurrentUser) -> dict[str, Any]:
    st = get_settings()
    return {
        "ai_enabled": st.ai_provider != "none",
        "ai_provider": st.ai_provider,
        "resolutions": RESOLUTIONS,
        "contract_schema": ContractSpec.model_json_schema(),
        "now": clock.now().isoformat(),
    }


# --- auth ---------------------------------------------------------------------------------------------


@router.get("/auth/dev-users", tags=["auth"])
def dev_users(s: DB) -> list[dict[str, str]]:
    if get_settings().auth_mode != "dev":
        raise Forbidden("Yalnızca geliştirme modunda")
    return [
        {"username": u.username, "display_name": u.display_name, "role": u.role}
        for u in s.scalars(select(User).where(User.active.is_(True)).order_by(User.role, User.username))
    ]


@router.post("/auth/dev-login", tags=["auth"])
def dev_login(body: LoginIn, s: DB) -> dict[str, Any]:
    if get_settings().auth_mode != "dev":
        raise Forbidden("Yalnızca geliştirme modunda; üretimde kurumsal kimlik sağlayıcı (OIDC) kullanılır")
    user = s.get(User, body.username)
    if user is None or not user.active:
        raise NotFound("Kullanıcı bulunamadı")
    audit(s, user.username, "auth.dev_login", "user", user.username)
    return {
        "token": issue_token(user),
        "user": {"username": user.username, "display_name": user.display_name, "role": user.role},
    }


@router.get("/auth/me", tags=["auth"])
def me(user: CurrentUser) -> dict[str, str]:
    return {"username": user.username, "display_name": user.display_name, "role": user.role}


# --- dashboards -----------------------------------------------------------------------------------------


@router.get("/overview", tags=["dashboard"])
def overview(s: DB, _: CurrentUser) -> dict[str, Any]:
    return analytics.overview(s)


@router.get("/insights", tags=["dashboard"])
def insights(s: DB, _: CurrentUser, days: int = Query(default=90, ge=7, le=365)) -> dict[str, Any]:
    return {**analytics.insights(s, days), "simulation_quality": analytics.simulation_quality(s)}


@router.get("/tuning", tags=["dashboard"])
def tuning_overview(s: DB, _: CurrentUser) -> list[dict[str, Any]]:
    from loadguard.services.contracts import tuning_suggestions

    out = []
    for inst in s.scalars(select(Institution).where(Institution.active.is_(True)).order_by(Institution.name)):
        for sg in tuning_suggestions(s, inst.id):
            out.append({"institution_id": str(inst.id), "institution": inst.name, **sg.to_dict()})
    return out


@router.get("/audit", tags=["dashboard"])
def audit_log(
    s: DB, _: CurrentUser, entity_id: str | None = None, limit: int = Query(default=100, le=500)
) -> list[dict[str, Any]]:
    q = select(AuditLog).order_by(AuditLog.at.desc()).limit(limit)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    return [
        {
            "at": iso(a.at),
            "actor": a.actor,
            "action": a.action,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "details": a.details,
        }
        for a in s.scalars(q)
    ]


# --- suppressions ---------------------------------------------------------------------------------------


@router.get("/suppressions", tags=["suppressions"])
def list_suppressions(s: DB, _: CurrentUser) -> list[dict[str, Any]]:
    rows = s.execute(
        select(Suppression, Institution.name)
        .outerjoin(Institution, Institution.id == Suppression.institution_id)
        .where(Suppression.ends_at >= clock.now())
        .order_by(Suppression.starts_at)
    ).all()
    return [
        {
            "id": str(x.id),
            "institution_id": str(x.institution_id) if x.institution_id else None,
            "institution": n or "Tüm kurumlar",
            "starts_at": iso(x.starts_at),
            "ends_at": iso(x.ends_at),
            "reason": x.reason,
            "created_by": x.created_by,
        }
        for x, n in rows
    ]


@router.post(
    "/suppressions", tags=["suppressions"], status_code=201, dependencies=[require_roles("APPROVER", "ADMIN")]
)
def create_suppression(body: SuppressionIn, s: DB, user: CurrentUser) -> dict[str, str]:
    if body.ends_at <= body.starts_at:
        raise Invalid("Bitiş başlangıçtan sonra olmalı")
    sup = Suppression(
        institution_id=uuid.UUID(body.institution_id) if body.institution_id else None,
        starts_at=body.starts_at,
        ends_at=body.ends_at,
        reason=body.reason,
        created_by=user.username,
    )
    s.add(sup)
    s.flush()
    audit(s, user.username, "suppression.created", "suppression", sup.id, reason=body.reason)
    return {"id": str(sup.id)}


# --- ingestion (machine-to-machine) -----------------------------------------------------------------------


@router.post("/ingest/loads", tags=["ingest"], status_code=202, dependencies=[Depends(ingest_auth)])
def ingest_load(body: LoadIn, s: DB) -> dict[str, Any]:
    load, created = pipeline.ingest(s, pipeline.LoadIn(**body.model_dump()))
    return {
        "load_id": str(load.id),
        "created": created,
        "status": "QUEUED" if created else "DUPLICATE_IGNORED",
    }
