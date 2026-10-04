"""Live pipeline: ingest -> assign -> evaluate -> persist decision -> reconcile incidents.

All evaluation logic lives in the pure domain engine; this module only loads inputs and stores outputs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from loadguard.core import clock
from loadguard.core.config import get_settings
from loadguard.core.errors import NotFound
from loadguard.core.logging import get_logger
from loadguard.core.time import ops_date
from loadguard.db.models import (
    Evaluation,
    Incident,
    InputSnapshot,
    Institution,
    Load,
    Occurrence,
    ShadowResult,
)
from loadguard.domain.challengers import CHALLENGERS
from loadguard.domain.contract import UNSCHEDULED_SLOT, ContractSpec, Severity
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.engine import EvalResult, evaluate
from loadguard.domain.matching import assign_load
from loadguard.domain.model import HistoryPoint
from loadguard.domain.replay import HISTORY_DAYS, NON_REPRESENTATIVE_CODES
from loadguard.domain.schedule import ExpectedOccurrence, expected_occurrences
from loadguard.domain.snapshot import fingerprint, to_payload
from loadguard.domain.systemic import DueOccurrence, detect_systemic
from loadguard.domain.triage import Priority, demote
from loadguard.services import incidents as incident_svc
from loadguard.services.common import audit, enqueue, get_calendar
from loadguard.services.contracts import effective_contract, to_facts

log = get_logger(__name__)


@dataclass(frozen=True)
class LoadIn:
    institution_code: str
    external_id: str
    received_at: datetime
    content_hash: str
    record_count: int
    total_amount: float
    customer_count: int
    zero_amount_count: int = 0
    negative_amount_count: int = 0
    duplicate_record_count: int = 0
    max_amount: float | None = None
    file_name: str | None = None
    slot_hint: str | None = None
    source: str = "API"


def ingest(s: Session, data: LoadIn) -> tuple[Load, bool]:
    """Idempotent on (institution, external_id). Evaluation happens asynchronously via the job queue."""
    inst = s.scalars(select(Institution).where(Institution.code == data.institution_code)).first()
    if inst is None:
        raise NotFound(f"Bilinmeyen kurum kodu: {data.institution_code}")
    existing = s.scalars(
        select(Load).where(Load.institution_id == inst.id, Load.external_id == data.external_id)
    ).first()
    if existing is not None:
        return existing, False
    load = Load(
        institution_id=inst.id,
        external_id=data.external_id,
        received_at=data.received_at,
        source=data.source,
        file_name=data.file_name,
        content_hash=data.content_hash,
        slot_hint=data.slot_hint,
        record_count=data.record_count,
        total_amount=Decimal(str(data.total_amount)),
        customer_count=data.customer_count,
        zero_amount_count=data.zero_amount_count,
        negative_amount_count=data.negative_amount_count,
        duplicate_record_count=data.duplicate_record_count,
        max_amount=Decimal(str(data.max_amount)) if data.max_amount is not None else None,
    )
    s.add(load)
    s.flush()
    enqueue(s, "EVALUATE_LOAD", {"load_id": str(load.id)}, dedupe_key=f"load:{load.id}")
    return load, True


def _ensure_occurrence(
    s: Session, inst_id: uuid.UUID, slot_key: str, bd: date, expected: ExpectedOccurrence | None
) -> Occurrence:
    stmt = (
        insert(Occurrence)
        .values(
            id=uuid.uuid4(),
            institution_id=inst_id,
            slot_key=slot_key,
            business_date=bd,
            expected=expected is not None,
            window_start_utc=expected.window_start_utc if expected else None,
            deadline_utc=expected.deadline_utc if expected else None,
            status="PENDING" if expected else "UNSCHEDULED",
            metrics={},
            baselines={},
            findings=[],
            load_count=0,
            excluded_from_baseline=False,
            regime_break=False,
        )
        .on_conflict_do_nothing(index_elements=["institution_id", "slot_key", "business_date"])
    )
    s.execute(stmt)
    occ = s.scalars(
        select(Occurrence)
        .where(
            Occurrence.institution_id == inst_id,
            Occurrence.slot_key == slot_key,
            Occurrence.business_date == bd,
        )
        .with_for_update()
    ).one()
    return occ


def process_load(s: Session, load_id: uuid.UUID) -> Occurrence | None:
    load = s.get(Load, load_id)
    if load is None or load.occurrence_id is not None:
        return None
    # Serialise per institution so two files arriving together cannot claim the same slot.
    inst = s.scalars(select(Institution).where(Institution.id == load.institution_id).with_for_update()).one()
    tz_day = ops_date(load.received_at)
    eff = effective_contract(s, inst.id, tz_day)
    if eff is None:
        load.assignment_reason = "NO_CONTRACT"
        return None
    _, spec = eff
    cal = get_calendar(s, spec.calendar)
    lo, hi = tz_day - timedelta(days=6), tz_day + timedelta(days=2)
    filled = {
        (k, d)
        for k, d in s.execute(
            select(Occurrence.slot_key, Occurrence.business_date).where(
                Occurrence.institution_id == inst.id,
                Occurrence.business_date.between(lo, hi),
                Occurrence.load_count > 0,
            )
        )
    }
    a = assign_load(load.received_at, spec, cal, lambda k, d: (k, d) in filled, load.slot_hint)
    occ = _ensure_occurrence(s, inst.id, a.slot_key, a.business_date, a.expected)
    load.occurrence_id, load.assignment_reason = occ.id, a.reason
    occ.load_count += 1
    s.flush()
    evaluate_occurrence(s, inst, occ, trigger="LOAD")
    return occ


def _history(s: Session, occ: Occurrence, spec: ContractSpec) -> tuple[HistoryPoint, ...]:
    cal = get_calendar(s, spec.calendar)
    tz = ZoneInfo(spec.timezone)
    rows = s.scalars(
        select(Occurrence)
        .where(
            Occurrence.institution_id == occ.institution_id,
            Occurrence.slot_key == occ.slot_key,
            Occurrence.business_date < occ.business_date,
            Occurrence.business_date >= occ.business_date - timedelta(days=HISTORY_DAYS),
            Occurrence.expected.is_(True),
            Occurrence.load_count > 0,
        )
        .order_by(Occurrence.business_date)
    ).all()
    out = []
    for o in rows:
        if not o.metrics:
            continue
        codes = {f["code"] for f in o.findings or []}
        first_min = None
        if o.first_received_at is not None:
            lt = o.first_received_at.astimezone(tz)
            first_min = lt.hour * 60 + lt.minute
        out.append(
            HistoryPoint(
                business_date=o.business_date,
                weekday=o.business_date.isoweekday(),
                month_phase=cal.month_phase(o.business_date),
                metrics={k: float(v) for k, v in o.metrics.items()},
                first_arrival_minutes=first_min,
                excluded=o.excluded_from_baseline or bool(codes & NON_REPRESENTATIVE_CODES),
                regime_break=o.regime_break,
            )
        )
    return tuple(out)


def evaluate_occurrence(s: Session, inst: Institution, occ: Occurrence, *, trigger: str) -> EvalResult | None:
    eff = effective_contract(s, inst.id, occ.business_date)
    if eff is None:
        return None
    cv, spec = eff
    cal = get_calendar(s, spec.calendar)
    expected = None
    if occ.slot_key != UNSCHEDULED_SLOT:
        expected = next(
            (
                e
                for e in expected_occurrences(spec, cal, occ.business_date, occ.business_date)
                if e.slot_key == occ.slot_key
            ),
            None,
        )
    loads = s.scalars(select(Load).where(Load.occurrence_id == occ.id).order_by(Load.received_at)).all()
    facts = tuple(to_facts(lf) for lf in loads)
    seen: frozenset[str] = frozenset()
    if loads:
        hashes = [lf.content_hash for lf in loads]
        earlier = s.execute(
            select(Load.content_hash, Load.received_at).where(
                Load.institution_id == inst.id,
                Load.content_hash.in_(hashes),
                Load.id.notin_([lf.id for lf in loads]),
            )
        ).all()
        seen = frozenset(
            lf.content_hash
            for lf in loads
            if any(h == lf.content_hash and t < lf.received_at for h, t in earlier)
        )
    now = clock.now()
    ctx = EvalContext(
        spec=spec,
        calendar=cal,
        slot_key=occ.slot_key,
        business_date=occ.business_date,
        expected=expected,
        loads=facts,
        history=_history(s, occ, spec),
        seen_hashes=seen,
        now=now,
    )
    result = evaluate(ctx)
    findings = [f.to_dict() for f in result.findings]
    changed = occ.status != result.status.value or occ.findings != findings or occ.metrics != result.metrics
    occ.status = result.status.value
    occ.metrics, occ.baselines, occ.findings = result.metrics, result.baselines, findings
    occ.max_severity = result.max_severity
    occ.first_received_at = loads[0].received_at if loads else None
    occ.load_count = len(loads)
    occ.contract_version_id, occ.spec_hash, occ.evaluated_at = cv.id, cv.spec_hash, now
    if changed or trigger != "DEADLINE_SWEEP":
        sha = store_snapshot(s, ctx)
        s.add(
            Evaluation(
                occurrence_id=occ.id,
                trigger=trigger,
                evaluated_at=now,
                engine_version=result.engine_version,
                contract_version_id=cv.id,
                spec_hash=cv.spec_hash,
                inputs={"load_ids": [str(lf.id) for lf in loads], "history_points": len(ctx.history)},
                snapshot_sha=sha,
                result={
                    "status": result.status.value,
                    "findings": findings,
                    "metrics": result.metrics,
                    "baselines": result.baselines,
                },
            )
        )
    slot = spec.slot(occ.slot_key)
    label = slot.label if slot else "Takvim dışı teslimat"
    incident_svc.reconcile(s, inst=inst, occ=occ, result=result, slot_label=label)
    run_shadow(s, occ, ctx)
    return result


def store_snapshot(s: Session, ctx: EvalContext) -> str:
    payload = to_payload(ctx)
    sha = fingerprint(payload)
    s.execute(insert(InputSnapshot).values(sha256=sha, payload=payload).on_conflict_do_nothing())
    return sha


def run_shadow(s: Session, occ: Occurrence, ctx: EvalContext) -> None:
    """Evaluate challengers on the same inputs. A failing challenger must never affect the champion."""
    for name in get_settings().shadow_list():
        fn = CHALLENGERS.get(name)
        if fn is None:
            continue
        try:
            with s.begin_nested():
                r = fn(ctx)
                codes = sorted({f.code for f in r.findings if f.severity.rank >= Severity.WARNING.rank})
                s.execute(
                    insert(ShadowResult)
                    .values(
                        occurrence_id=occ.id,
                        challenger=name,
                        evaluated_at=ctx.now,
                        status=r.status.value,
                        codes=codes,
                        max_severity=r.max_severity,
                    )
                    .on_conflict_do_update(
                        constraint="uq_shadow_results_occurrence_challenger",
                        set_={
                            "evaluated_at": ctx.now,
                            "status": r.status.value,
                            "codes": codes,
                            "max_severity": r.max_severity,
                        },
                    )
                )
        except Exception:
            log.exception("shadow_failed", challenger=name, occurrence_id=str(occ.id))


# --- periodic work ------------------------------------------------------------------------------------


def materialize(s: Session, day: date) -> int:
    """Create PENDING occurrences for `day` so the board shows what is expected before anything arrives."""
    n = 0
    for inst in s.scalars(select(Institution).where(Institution.active.is_(True))):
        eff = effective_contract(s, inst.id, day)
        if eff is None:
            continue
        spec: ContractSpec = eff[1]
        for e in expected_occurrences(spec, get_calendar(s, spec.calendar), day, day):
            _ensure_occurrence(s, inst.id, e.slot_key, e.business_date, e)
            n += 1
    return n


def sweep(s: Session) -> int:
    """Re-evaluate open occurrences whose window has started: AT_RISK before, MISSING after the deadline."""
    now = clock.now()
    rows = s.scalars(
        select(Occurrence)
        .where(
            Occurrence.status.in_(["PENDING", "AT_RISK"]),
            Occurrence.expected.is_(True),
            Occurrence.window_start_utc <= now,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for occ in rows:
        inst = s.get(Institution, occ.institution_id)
        assert inst is not None
        evaluate_occurrence(s, inst, occ, trigger="DEADLINE_SWEEP")
    return len(rows)


def systemic_check(s: Session) -> Incident | None:
    now = clock.now()
    rows = s.execute(
        select(Occurrence, Institution.name)
        .join(Institution, Institution.id == Occurrence.institution_id)
        .where(Occurrence.expected.is_(True), Occurrence.deadline_utc.between(now - timedelta(hours=2), now))
    ).all()
    due = [DueOccurrence(str(o.id), name, o.deadline_utc, o.status == "MISSING") for o, name in rows]
    sig = detect_systemic(due, now)
    if sig is None:
        return None
    day = ops_date(now)
    fingerprint = f"systemic:{day.isoformat()}"
    parent = s.scalars(
        select(Incident).where(Incident.fingerprint == fingerprint, Incident.status != "RESOLVED")
    ).first()
    names = ", ".join(sorted({m.institution_name for m in sig.missing}))
    if parent is None:
        parent = Incident(
            kind="SYSTEMIC",
            fingerprint=fingerprint,
            category="TIMELINESS",
            codes=["SYSTEMIC_OUTAGE"],
            title=f"Toplu teslimat kesintisi: {len(sig.missing)} kurumdan dosya gelmedi ({day:%d.%m.%Y})",
            status="OPEN",
            severity="CRITICAL",
            priority="P1",
            opened_at=now,
            updated_at=now,
        )
        s.add(parent)
        s.flush()
        incident_svc.add_event(
            s,
            parent,
            "system",
            "OPENED",
            f"Son 90 dakikada son teslim saati dolan {sig.due_total} teslimatın {len(sig.missing)}'i gelmedi "
            f"({names}). Ortak neden (SFTP/ağ/entegrasyon) olasılığı yüksek; kurumları tek tek aramadan önce "
            "kendi alım altyapımızı kontrol edin.",
        )
        enqueue(s, "AI_BRIEF", {"incident_id": str(parent.id)}, dedupe_key=f"brief:{parent.id}")
        enqueue(s, "NOTIFY", {"incident_id": str(parent.id)}, dedupe_key=f"notify:{parent.id}")
        audit(s, "system", "incident.systemic_opened", "incident", parent.id, missing=len(sig.missing))
    occ_ids = [uuid.UUID(m.occurrence_id) for m in sig.missing]
    for child in s.scalars(
        select(Incident).where(
            Incident.occurrence_id.in_(occ_ids), Incident.status != "RESOLVED", Incident.parent_id.is_(None)
        )
    ):
        child.parent_id = parent.id
        child.priority = demote(Priority(child.priority)).value
        incident_svc.add_event(
            s,
            child,
            "system",
            "LINKED",
            f"Toplu kesinti olayına (#{parent.number}) bağlandı; öncelik düşürüldü.",
        )
    return parent
