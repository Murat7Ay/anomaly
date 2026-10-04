from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from loadguard.ai.briefing import brief_view, generate_brief
from loadguard.api.deps import DB, CurrentUser
from loadguard.api.schemas import AssignIn, CommentIn, ResolveIn, iso
from loadguard.db.models import Evaluation, Incident, IncidentEvent, Institution, Load, Occurrence
from loadguard.services import incidents as svc
from loadguard.services.analytics import institution_series
from loadguard.services.contracts import effective_contract

router = APIRouter(prefix="/incidents", tags=["incidents"])


def incident_row(inc: Incident, inst_name: str | None) -> dict[str, Any]:
    return {
        "id": str(inc.id),
        "number": inc.number,
        "kind": inc.kind,
        "title": inc.title,
        "status": inc.status,
        "severity": inc.severity,
        "priority": inc.priority,
        "category": inc.category,
        "codes": inc.codes,
        "institution_id": str(inc.institution_id) if inc.institution_id else None,
        "institution": inst_name,
        "occurrence_id": str(inc.occurrence_id) if inc.occurrence_id else None,
        "parent_id": str(inc.parent_id) if inc.parent_id else None,
        "impact_customers": inc.impact_customers,
        "impact_amount": inc.impact_amount,
        "opened_at": iso(inc.opened_at),
        "updated_at": iso(inc.updated_at),
        "acknowledged_at": iso(inc.acknowledged_at),
        "acknowledged_by": inc.acknowledged_by,
        "assignee": inc.assignee,
        "resolved_at": iso(inc.resolved_at),
        "resolved_by": inc.resolved_by,
        "resolution": inc.resolution,
        "resolution_note": inc.resolution_note,
    }


@router.get("")
def list_incidents(
    s: DB,
    _: CurrentUser,
    status: list[str] = Query(default=[]),
    priority: list[str] = Query(default=[]),
    category: list[str] = Query(default=[]),
    institution_id: uuid.UUID | None = None,
    q: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
) -> dict[str, Any]:
    stmt = select(Incident, Institution.name).outerjoin(
        Institution, Institution.id == Incident.institution_id
    )
    if status:
        stmt = stmt.where(Incident.status.in_(status))
    if priority:
        stmt = stmt.where(Incident.priority.in_(priority))
    if category:
        stmt = stmt.where(Incident.category.in_(category))
    if institution_id:
        stmt = stmt.where(Incident.institution_id == institution_id)
    if q:
        stmt = stmt.where(Incident.title.ilike(f"%{q}%"))
    total = s.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = s.execute(
        stmt.order_by(
            (Incident.status == "RESOLVED").asc(), Incident.priority.asc(), Incident.opened_at.desc()
        )
        .limit(limit)
        .offset(offset)
    ).all()
    return {"total": total, "items": [incident_row(i, n) for i, n in rows]}


@router.get("/{incident_id}")
def get_incident(incident_id: uuid.UUID, s: DB, _: CurrentUser) -> dict[str, Any]:
    inc = svc.get_incident(s, incident_id)
    inst = s.get(Institution, inc.institution_id) if inc.institution_id else None
    events = s.scalars(
        select(IncidentEvent).where(IncidentEvent.incident_id == inc.id).order_by(IncidentEvent.at)
    ).all()
    out = incident_row(inc, inst.name if inst else None)
    out["events"] = [
        {"at": iso(e.at), "actor": e.actor, "kind": e.kind, "message": e.message, "data": e.data}
        for e in events
    ]
    out["children"] = [
        incident_row(c, n)
        for c, n in s.execute(
            select(Incident, Institution.name)
            .outerjoin(Institution, Institution.id == Incident.institution_id)
            .where(Incident.parent_id == inc.id)
        )
    ]
    if inst:
        out["institution_detail"] = {
            "id": str(inst.id),
            "code": inst.code,
            "name": inst.name,
            "tier": inst.tier,
            "sector": inst.sector,
            "contact_email": inst.contact_email,
        }
    if inc.occurrence_id:
        occ = s.get(Occurrence, inc.occurrence_id)
        assert occ is not None
        eff = effective_contract(s, occ.institution_id, occ.business_date)
        slot = eff[1].slot(occ.slot_key) if eff else None
        loads = s.scalars(select(Load).where(Load.occurrence_id == occ.id).order_by(Load.received_at)).all()
        out["occurrence"] = {
            "id": str(occ.id),
            "slot_key": occ.slot_key,
            "slot_label": slot.label if slot else "Takvim dışı",
            "business_date": occ.business_date.isoformat(),
            "status": occ.status,
            "expected": occ.expected,
            "window_start_utc": iso(occ.window_start_utc),
            "deadline_utc": iso(occ.deadline_utc),
            "first_received_at": iso(occ.first_received_at),
            "metrics": occ.metrics,
            "baselines": occ.baselines,
            "findings": occ.findings,
            "spec_hash": occ.spec_hash,
            "excluded": occ.excluded_from_baseline,
            "regime_break": occ.regime_break,
            "loads": [
                {
                    "id": str(lf.id),
                    "received_at": iso(lf.received_at),
                    "file_name": lf.file_name,
                    "record_count": lf.record_count,
                    "total_amount": float(lf.total_amount),
                    "customer_count": lf.customer_count,
                    "assignment_reason": lf.assignment_reason,
                    "content_hash": lf.content_hash[:16],
                }
                for lf in loads
            ],
        }
        out["evaluations"] = [
            {
                "id": str(e.id),
                "trigger": e.trigger,
                "evaluated_at": iso(e.evaluated_at),
                "engine_version": e.engine_version,
                "verifiable": e.snapshot_sha is not None,
            }
            for e in s.scalars(
                select(Evaluation)
                .where(Evaluation.occurrence_id == occ.id)
                .order_by(Evaluation.evaluated_at.desc())
            )
        ]
        out["series"] = [
            p
            for p in institution_series(s, occ.institution_id, "record_count", 120)
            if p["slot_key"] == occ.slot_key
        ]
    return out


@router.get("/{incident_id}/brief")
def get_brief(incident_id: uuid.UUID, s: DB, _: CurrentUser) -> dict[str, Any]:
    return brief_view(s, svc.get_incident(s, incident_id))


@router.post("/{incident_id}/brief")
def regenerate_brief(incident_id: uuid.UUID, s: DB, user: CurrentUser) -> dict[str, Any]:
    inc = svc.get_incident(s, incident_id)
    generate_brief(s, inc.id, actor=user.username)
    return brief_view(s, inc)


@router.post("/{incident_id}/acknowledge")
def acknowledge(incident_id: uuid.UUID, s: DB, user: CurrentUser) -> dict[str, Any]:
    return incident_row(svc.acknowledge(s, actor=user.username, incident_id=incident_id), None)


@router.post("/{incident_id}/assign")
def assign(incident_id: uuid.UUID, body: AssignIn, s: DB, user: CurrentUser) -> dict[str, Any]:
    return incident_row(
        svc.assign(s, actor=user.username, incident_id=incident_id, assignee=body.assignee), None
    )


@router.post("/{incident_id}/comments")
def add_comment(incident_id: uuid.UUID, body: CommentIn, s: DB, user: CurrentUser) -> dict[str, Any]:
    return incident_row(svc.comment(s, actor=user.username, incident_id=incident_id, text=body.text), None)


@router.post("/{incident_id}/resolve")
def resolve(incident_id: uuid.UUID, body: ResolveIn, s: DB, user: CurrentUser) -> dict[str, Any]:
    inc = svc.resolve(
        s, actor=user.username, incident_id=incident_id, resolution=body.resolution, note=body.note
    )
    return incident_row(inc, None)
