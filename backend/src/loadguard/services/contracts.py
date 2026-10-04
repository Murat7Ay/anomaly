"""Contract lifecycle: draft -> pending approval (with backtest) -> approved, under four-eyes control."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from loadguard.core import clock
from loadguard.core.errors import Conflict, Forbidden, Invalid, NotFound
from loadguard.db.models import ContractVersion, Incident, Institution, Load, Occurrence
from loadguard.domain.backtest import Verdict, run_backtest
from loadguard.domain.contract import ContractSpec
from loadguard.domain.inference import InferredContract, infer_contract
from loadguard.domain.model import LoadFacts
from loadguard.domain.replay import Label
from loadguard.domain.schedule import local_date
from loadguard.domain.tuning import ResolvedFinding, Suggestion, suggest_tuning
from loadguard.services.common import audit, get_calendar

APPROVER_ROLES = {"APPROVER", "ADMIN"}


def effective_contract(
    s: Session, institution_id: uuid.UUID, on: date
) -> tuple[ContractVersion, ContractSpec] | None:
    cv = s.scalars(
        select(ContractVersion)
        .where(
            ContractVersion.institution_id == institution_id,
            ContractVersion.status == "APPROVED",
            ContractVersion.effective_from <= on,
        )
        .order_by(ContractVersion.effective_from.desc(), ContractVersion.version.desc())
        .limit(1)
    ).first()
    return (cv, ContractSpec.model_validate(cv.spec)) if cv else None


def _get(s: Session, version_id: uuid.UUID, *, lock: bool = False) -> ContractVersion:
    q = select(ContractVersion).where(ContractVersion.id == version_id)
    cv = s.scalars(q.with_for_update() if lock else q).first()
    if cv is None:
        raise NotFound("Sözleşme sürümü bulunamadı")
    return cv


def create_draft(
    s: Session,
    *,
    actor: str,
    institution_id: uuid.UUID,
    spec: ContractSpec,
    effective_from: date,
    change_note: str | None,
    origin: str = "MANUAL",
) -> ContractVersion:
    if s.get(Institution, institution_id) is None:
        raise NotFound("Kurum bulunamadı")
    next_v = (
        s.scalar(
            select(func.max(ContractVersion.version)).where(ContractVersion.institution_id == institution_id)
        )
        or 0
    ) + 1
    cv = ContractVersion(
        institution_id=institution_id,
        version=next_v,
        status="DRAFT",
        effective_from=effective_from,
        spec=spec.canonical(),
        spec_hash=spec.spec_hash(),
        origin=origin,
        change_note=change_note,
        created_by=actor,
    )
    s.add(cv)
    s.flush()
    audit(s, actor, "contract.draft_created", "contract_version", cv.id, version=next_v, origin=origin)
    return cv


def update_draft(
    s: Session,
    *,
    actor: str,
    version_id: uuid.UUID,
    spec: ContractSpec,
    effective_from: date,
    change_note: str | None,
) -> ContractVersion:
    cv = _get(s, version_id, lock=True)
    if cv.status != "DRAFT":
        raise Conflict("Yalnızca taslak sürümler düzenlenebilir")
    cv.spec, cv.spec_hash, cv.effective_from, cv.change_note = (
        spec.canonical(),
        spec.spec_hash(),
        effective_from,
        change_note,
    )
    cv.backtest = None
    audit(s, actor, "contract.draft_updated", "contract_version", cv.id)
    return cv


def submit(s: Session, *, actor: str, version_id: uuid.UUID) -> ContractVersion:
    cv = _get(s, version_id, lock=True)
    if cv.status != "DRAFT":
        raise Conflict("Yalnızca taslak sürümler onaya gönderilebilir")
    cv.backtest = backtest(s, cv.institution_id, ContractSpec.model_validate(cv.spec))
    cv.status, cv.submitted_at = "PENDING_APPROVAL", clock.now()
    audit(s, actor, "contract.submitted", "contract_version", cv.id)
    return cv


def decide(
    s: Session, *, actor: str, role: str, version_id: uuid.UUID, approve: bool, note: str | None
) -> ContractVersion:
    cv = _get(s, version_id, lock=True)
    if role not in APPROVER_ROLES:
        raise Forbidden("Onay yetkiniz yok")
    if cv.status != "PENDING_APPROVAL":
        raise Conflict("Sürüm onay beklemiyor")
    if cv.created_by == actor:
        raise Forbidden("Dört göz ilkesi: kendi hazırladığınız sürümü onaylayamazsınız")
    if not approve and not (note and note.strip()):
        raise Invalid("Ret gerekçesi zorunludur")
    today = local_date(clock.now(), "Europe/Istanbul")
    cv.status = "APPROVED" if approve else "REJECTED"
    cv.decided_by, cv.decided_at, cv.decision_note = actor, clock.now(), note
    if approve and cv.effective_from < today:
        cv.effective_from = today  # never rewrite history: approvals apply from today onwards
    audit(
        s,
        actor,
        "contract.approved" if approve else "contract.rejected",
        "contract_version",
        cv.id,
        note=note,
    )
    return cv


def withdraw(s: Session, *, actor: str, version_id: uuid.UUID) -> ContractVersion:
    cv = _get(s, version_id, lock=True)
    if cv.status not in ("DRAFT", "PENDING_APPROVAL"):
        raise Conflict("Bu sürüm geri çekilemez")
    cv.status = "WITHDRAWN"
    audit(s, actor, "contract.withdrawn", "contract_version", cv.id)
    return cv


# --- analysis helpers -----------------------------------------------------------------------------


def load_facts(s: Session, institution_id: uuid.UUID, since: datetime) -> list[LoadFacts]:
    rows = s.scalars(
        select(Load)
        .where(Load.institution_id == institution_id, Load.received_at >= since)
        .order_by(Load.received_at)
    ).all()
    return [to_facts(r) for r in rows]


def to_facts(r: Load) -> LoadFacts:
    return LoadFacts(
        id=str(r.id),
        received_at=r.received_at,
        content_hash=r.content_hash,
        record_count=int(r.record_count),
        total_amount=float(r.total_amount),
        customer_count=int(r.customer_count),
        zero_amount_count=int(r.zero_amount_count),
        negative_amount_count=int(r.negative_amount_count),
        duplicate_record_count=int(r.duplicate_record_count),
        max_amount=float(r.max_amount) if r.max_amount is not None else None,
    )


def _labels_and_verdicts(
    s: Session, institution_id: uuid.UUID
) -> tuple[dict[tuple[str, date], str], list[Verdict]]:
    labels: dict[tuple[str, date], str] = {}
    for o in s.scalars(
        select(Occurrence).where(
            Occurrence.institution_id == institution_id,
            (Occurrence.excluded_from_baseline.is_(True)) | (Occurrence.regime_break.is_(True)),
        )
    ):
        labels[(o.slot_key, o.business_date)] = Label.REGIME if o.regime_break else Label.EXCLUDE
    verdicts = [
        Verdict(slot, bd, cat, res)
        for slot, bd, cat, res in s.execute(
            select(Occurrence.slot_key, Occurrence.business_date, Incident.category, Incident.resolution)
            .join(Incident, Incident.occurrence_id == Occurrence.id)
            .where(
                Incident.institution_id == institution_id,
                Incident.status == "RESOLVED",
                Incident.resolution.in_(["TRUE_POSITIVE", "FALSE_POSITIVE", "EXPECTED_EVENT", "NEW_NORMAL"]),
            )
        )
    ]
    return labels, verdicts


def backtest(
    s: Session, institution_id: uuid.UUID, candidate: ContractSpec, days: int = 90
) -> dict[str, Any]:
    now = clock.now()
    today = local_date(now, candidate.timezone)
    start, end = today - timedelta(days=days), today - timedelta(days=1)
    current = effective_contract(s, institution_id, today)
    labels, verdicts = _labels_and_verdicts(s, institution_id)
    loads = load_facts(s, institution_id, now - timedelta(days=days + 420))
    result = run_backtest(
        candidate=candidate,
        current=current[1] if current else None,
        calendar=get_calendar(s, candidate.calendar),
        loads=loads,
        start=start,
        end=end,
        now=now,
        history_labels=labels,
        verdicts=verdicts,
    )
    result["computed_at"] = now.isoformat()
    result["current_version"] = current[0].version if current else None
    return result


def infer_from_history(s: Session, institution_id: uuid.UUID, days: int = 180) -> InferredContract:
    now = clock.now()
    arrivals = list(
        s.scalars(
            select(Load.received_at).where(
                Load.institution_id == institution_id, Load.received_at >= now - timedelta(days=days)
            )
        )
    )
    today = local_date(now, "Europe/Istanbul")
    return infer_contract(
        arrivals, get_calendar(s), start=today - timedelta(days=days), end=today - timedelta(days=1)
    )


def tuning_suggestions(s: Session, institution_id: uuid.UUID, days: int = 120) -> list[Suggestion]:
    eff = effective_contract(s, institution_id, local_date(clock.now(), "Europe/Istanbul"))
    if eff is None:
        return []
    since = clock.now() - timedelta(days=days)
    rows = s.execute(
        select(Incident.resolution, Occurrence.slot_key, Occurrence.findings)
        .join(Occurrence, Incident.occurrence_id == Occurrence.id)
        .where(
            Incident.institution_id == institution_id,
            Incident.status == "RESOLVED",
            Incident.resolved_at >= since,
            Incident.resolution.in_(["TRUE_POSITIVE", "FALSE_POSITIVE", "NEW_NORMAL"]),
        )
    ).all()
    resolved: list[ResolvedFinding] = []
    for resolution, slot_key, findings in rows:
        for f in findings or []:
            if f["severity"] in ("WARNING", "CRITICAL"):
                resolved.append(
                    ResolvedFinding(
                        f["code"],
                        f.get("metric"),
                        slot_key,
                        resolution,
                        f.get("observed"),
                        f.get("evidence") or {},
                    )
                )
    return suggest_tuning(eff[1], resolved)
