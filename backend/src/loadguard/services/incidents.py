"""Incident lifecycle and state reconciliation.

Each evaluation *reconciles* incidents with the occurrence's current findings:
  new problem -> open; changed -> update (with timeline event); gone -> auto-resolve.
So a partial file followed by its complement closes itself, and MISSING turns into LATE on arrival.
Analyst verdicts feed back into learning (baseline exclusion / regime change) and tuning.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from loadguard.core import clock
from loadguard.core.errors import Conflict, Invalid, NotFound
from loadguard.db.models import Incident, IncidentEvent, Institution, Occurrence, Suppression
from loadguard.domain import fmt
from loadguard.domain.contract import Severity
from loadguard.domain.engine import EvalResult
from loadguard.domain.model import Finding
from loadguard.domain.triage import Priority, demote, estimate_impact, priority_for
from loadguard.services.common import audit, enqueue

CODE_TITLES = {
    "MISSING_DELIVERY": "dosya gelmedi",
    "DELIVERY_AT_RISK": "dosya gecikme riski",
    "LATE_DELIVERY": "dosya geç geldi",
    "EARLY_DELIVERY": "dosya erken geldi",
    "ARRIVAL_DRIFT": "varış saati kayıyor",
    "UNEXPECTED_DELIVERY": "takvim dışı teslimat",
    "VOLUME_LOW": "hacim beklenenden düşük",
    "VOLUME_HIGH": "hacim beklenenden yüksek",
    "UNIT_SCALE_SUSPECT": "tutar birim hatası şüphesi",
    "DUPLICATE_FILE": "mükerrer dosya",
    "STALE_DATA": "güncellenmemiş veri",
    "ZERO_AMOUNT_RECORDS": "sıfır tutarlı kayıtlar",
    "NEGATIVE_AMOUNTS": "negatif tutarlı kayıtlar",
    "DUPLICATE_RECORDS": "mükerrer kayıtlar",
    "LIMIT_BREACH": "kural ihlali",
}
CODE_ORDER = list(CODE_TITLES)

RESOLUTIONS = {
    "TRUE_POSITIVE": "Gerçek sorun",
    "FALSE_POSITIVE": "Yanlış alarm",
    "EXPECTED_EVENT": "Bilinen / planlı olay",
    "NEW_NORMAL": "Kalıcı değişim (yeni normal)",
    "DUPLICATE": "Başka bir olayın tekrarı",
}
SYSTEM_RESOLUTIONS = {
    "AUTO_CLEARED": "Koşul kendiliğinden düzeldi",
    "SUPPRESSED": "Bakım/planlı olay kapsamında",
}


def add_event(s: Session, inc: Incident, actor: str, kind: str, message: str, **data: Any) -> None:
    s.add(
        IncidentEvent(incident_id=inc.id, at=clock.now(), actor=actor, kind=kind, message=message, data=data)
    )


def _title(inst: Institution, occ: Occurrence, findings: list[Finding], slot_label: str) -> str:
    codes = sorted({f.code for f in findings}, key=CODE_ORDER.index)
    what = ", ".join(CODE_TITLES.get(c, c) for c in codes)
    return f"{inst.name} — {slot_label}: {what} ({occ.business_date:%d.%m.%Y})"


def _active_suppression(s: Session, inst_id: uuid.UUID) -> Suppression | None:
    now = clock.now()
    return s.scalars(
        select(Suppression).where(
            (Suppression.institution_id == inst_id) | Suppression.institution_id.is_(None),
            Suppression.starts_at <= now,
            Suppression.ends_at >= now,
        )
    ).first()


def reconcile(
    s: Session, *, inst: Institution, occ: Occurrence, result: EvalResult, slot_label: str
) -> list[Incident]:
    now = clock.now()
    actionable = [f for f in result.findings if f.severity.rank >= Severity.WARNING.rank]
    by_cat: dict[str, list[Finding]] = defaultdict(list)
    for f in actionable:
        by_cat[f.category.value].append(f)

    existing = {
        i.category: i
        for i in s.scalars(
            select(Incident)
            .where(Incident.occurrence_id == occ.id, Incident.status != "RESOLVED")
            .with_for_update()
        )
    }
    touched: list[Incident] = []
    reference = result.baselines.get("reference") or {}

    for cat, fs in by_cat.items():
        codes = sorted({f.code for f in fs})
        sev = max(fs, key=lambda f: f.severity.rank).severity
        impact = estimate_impact(fs, result.metrics, reference)
        prio = priority_for(sev, inst.tier, impact)
        title = _title(inst, occ, fs, slot_label)
        summary = [f.message for f in fs]
        inc = existing.get(cat)
        if inc is not None:
            if inc.codes != codes or inc.severity != sev.value:
                if inc.parent_id is not None:
                    prio = demote(prio)
                add_event(
                    s,
                    inc,
                    "system",
                    "UPDATED",
                    "Bulgular güncellendi: " + " | ".join(summary),
                    codes=codes,
                    previous_codes=inc.codes,
                )
                inc.codes, inc.severity, inc.priority, inc.title = codes, sev.value, prio.value, title
                inc.impact_customers, inc.impact_amount = impact.customers, impact.amount
                inc.updated_at = now
                touched.append(inc)
            continue

        fingerprint = f"{occ.id}:{cat}"
        last = s.scalars(
            select(Incident)
            .where(Incident.fingerprint == fingerprint, Incident.status == "RESOLVED")
            .order_by(Incident.resolved_at.desc())
            .limit(1)
        ).first()
        if last is not None and set(codes) <= set(last.codes) and last.resolution != "AUTO_CLEARED":
            continue  # an analyst already decided on exactly this; don't nag

        sup = _active_suppression(s, inst.id)
        inc = Incident(
            kind="OCCURRENCE",
            institution_id=inst.id,
            occurrence_id=occ.id,
            fingerprint=fingerprint,
            category=cat,
            codes=codes,
            title=title,
            status="RESOLVED" if sup else "OPEN",
            severity=sev.value,
            priority=prio.value,
            impact_customers=impact.customers,
            impact_amount=impact.amount,
            opened_at=now,
            updated_at=now,
            resolved_at=now if sup else None,
            resolution="SUPPRESSED" if sup else None,
            resolved_by="system" if sup else None,
            suppressed_by=sup.id if sup else None,
        )
        s.add(inc)
        s.flush()
        add_event(s, inc, "system", "OPENED", " | ".join(summary), codes=codes, impact=impact.to_dict())
        if sup:
            add_event(
                s, inc, "system", "SUPPRESSED", f"Bakım/planlı olay kapsamında bastırıldı: {sup.reason}"
            )
        else:
            enqueue(s, "AI_BRIEF", {"incident_id": str(inc.id)}, dedupe_key=f"brief:{inc.id}")
            if Priority(prio).rank <= 2:
                # Short delay: lets systemic grouping and quick self-healing happen before anyone is paged.
                enqueue(
                    s,
                    "NOTIFY",
                    {"incident_id": str(inc.id)},
                    dedupe_key=f"notify:{inc.id}",
                    run_at=now + timedelta(minutes=2),
                )
        touched.append(inc)

    for cat, inc in existing.items():
        if cat not in by_cat:
            inc.status, inc.resolution, inc.resolved_at, inc.resolved_by = (
                "RESOLVED",
                "AUTO_CLEARED",
                now,
                "system",
            )
            inc.updated_at = now
            add_event(
                s,
                inc,
                "system",
                "AUTO_RESOLVED",
                "Koşul ortadan kalktı (ör. tamamlayıcı dosya geldi veya veri düzeldi); olay otomatik kapatıldı.",
            )
            touched.append(inc)
    return touched


# --- analyst actions --------------------------------------------------------------------------------


def get_incident(s: Session, incident_id: uuid.UUID, *, lock: bool = False) -> Incident:
    q = select(Incident).where(Incident.id == incident_id)
    inc = s.scalars(q.with_for_update() if lock else q).first()
    if inc is None:
        raise NotFound("Olay bulunamadı")
    return inc


def acknowledge(s: Session, *, actor: str, incident_id: uuid.UUID) -> Incident:
    inc = get_incident(s, incident_id, lock=True)
    if inc.status != "OPEN":
        raise Conflict("Olay zaten üstlenilmiş veya kapatılmış")
    now = clock.now()
    inc.status, inc.acknowledged_at, inc.acknowledged_by, inc.updated_at = "ACKNOWLEDGED", now, actor, now
    inc.assignee = inc.assignee or actor
    add_event(s, inc, actor, "ACKNOWLEDGED", f"{actor} olayı üstlendi.")
    audit(s, actor, "incident.acknowledged", "incident", inc.id)
    return inc


def assign(s: Session, *, actor: str, incident_id: uuid.UUID, assignee: str | None) -> Incident:
    inc = get_incident(s, incident_id, lock=True)
    inc.assignee, inc.updated_at = assignee, clock.now()
    add_event(s, inc, actor, "ASSIGNED", f"Sorumlu: {assignee or '—'}")
    audit(s, actor, "incident.assigned", "incident", inc.id, assignee=assignee)
    return inc


def comment(s: Session, *, actor: str, incident_id: uuid.UUID, text: str) -> Incident:
    if not text.strip():
        raise Invalid("Yorum boş olamaz")
    inc = get_incident(s, incident_id)
    inc.updated_at = clock.now()
    add_event(s, inc, actor, "COMMENT", text.strip()[:4000])
    return inc


def resolve(s: Session, *, actor: str, incident_id: uuid.UUID, resolution: str, note: str | None) -> Incident:
    if resolution not in RESOLUTIONS:
        raise Invalid("Geçersiz çözüm türü", allowed=list(RESOLUTIONS))
    if resolution in ("FALSE_POSITIVE", "NEW_NORMAL", "EXPECTED_EVENT") and not (note and note.strip()):
        raise Invalid("Bu karar için açıklama zorunludur (öğrenme ve denetim izi için)")
    inc = get_incident(s, incident_id, lock=True)
    if inc.status == "RESOLVED":
        raise Conflict("Olay zaten kapatılmış")
    _close(s, inc, actor, resolution, note)
    if inc.kind == "SYSTEMIC":
        for child in s.scalars(
            select(Incident).where(Incident.parent_id == inc.id, Incident.status != "RESOLVED")
        ):
            _close(
                s,
                child,
                actor,
                resolution,
                f"Üst olay #{inc.number} ile birlikte kapatıldı. {note or ''}".strip(),
            )
    return inc


def _close(s: Session, inc: Incident, actor: str, resolution: str, note: str | None) -> None:
    now = clock.now()
    inc.status, inc.resolution, inc.resolution_note = "RESOLVED", resolution, note
    inc.resolved_at, inc.resolved_by, inc.updated_at = now, actor, now
    add_event(
        s,
        inc,
        actor,
        "RESOLVED",
        f"Karar: {RESOLUTIONS[resolution]}" + (f" — {note}" if note else ""),
        resolution=resolution,
    )
    audit(s, actor, "incident.resolved", "incident", inc.id, resolution=resolution, note=note)
    if inc.occurrence_id is None:
        return
    occ = s.get(Occurrence, inc.occurrence_id)
    if occ is None:
        return
    # Feedback into learning: confirmed problems and one-off events must not become "normal".
    if resolution in ("TRUE_POSITIVE", "EXPECTED_EVENT") and inc.category in ("VOLUME", "QUALITY", "RULE"):
        occ.excluded_from_baseline = True
        add_event(s, inc, "system", "LEARNING", "Bu teslimat beklenen değer hesaplarından çıkarıldı.")
    elif resolution == "NEW_NORMAL":
        occ.regime_break = True
        add_event(
            s,
            inc,
            "system",
            "LEARNING",
            "Yeni normal işaretlendi: beklenen seviye bu teslimattan itibaren yeniden öğrenilecek.",
        )


def describe_impact(inc: Incident) -> str | None:
    if not inc.impact_customers:
        return None
    s = f"~{fmt.num(inc.impact_customers)} müşteri"
    if inc.impact_amount:
        s += f", ~{fmt.money(inc.impact_amount)} borç"
    return s
