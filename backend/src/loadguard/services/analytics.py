"""Read models for the operator UI: today's board, health, trends, detector quality."""

from __future__ import annotations

import statistics
import uuid
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from loadguard.core import clock
from loadguard.core.time import ops_today, ops_tz
from loadguard.db.models import ContractVersion, Incident, Institution, Load, Occurrence, SimTruth
from loadguard.domain.contract_migrations import load_spec
from loadguard.services.contracts import effective_contract

LABELLED = ("TRUE_POSITIVE", "FALSE_POSITIVE", "EXPECTED_EVENT", "NEW_NORMAL")
EXPECTED_CODES = {
    "MISSING": {"MISSING_DELIVERY"},
    "LATE": {"LATE_DELIVERY"},
    "PARTIAL": {"VOLUME_LOW"},
    "SPIKE": {"VOLUME_HIGH", "LIMIT_BREACH"},
    "UNIT_SCALE": {"UNIT_SCALE_SUSPECT"},
    "DUPLICATE_FILE": {"DUPLICATE_FILE"},
    "STALE": {"STALE_DATA"},
    "ZERO_AMOUNTS": {"ZERO_AMOUNT_RECORDS"},
    "NEGATIVE": {"NEGATIVE_AMOUNTS"},
    "UNEXPECTED": {"UNEXPECTED_DELIVERY"},
    "SYSTEMIC_OUTAGE": {"LATE_DELIVERY"},
}


def today() -> date:
    return ops_today()


def _minutes(ts: datetime | None) -> int | None:
    if ts is None:
        return None
    lt = ts.astimezone(ops_tz())
    return lt.hour * 60 + lt.minute


def _median_minutes(pairs: list[tuple[datetime, datetime | None]]) -> float | None:
    vals = [(b - a).total_seconds() / 60 for a, b in pairs if b is not None]
    return round(statistics.median(vals), 1) if vals else None


def _slot_labels(s: Session) -> dict[tuple[uuid.UUID, str], str]:
    out: dict[tuple[uuid.UUID, str], str] = {}
    for inst_id in s.scalars(select(Institution.id)):
        eff = effective_contract(s, inst_id, today())
        if eff:
            for sl in eff[1].slots:
                out[(inst_id, sl.key)] = sl.label
    return out


def overview(s: Session) -> dict[str, Any]:
    now, d = clock.now(), today()
    open_incs = s.execute(
        select(Incident.priority, func.count())
        .where(Incident.status != "RESOLVED")
        .group_by(Incident.priority)
    ).all()
    rows = s.execute(
        select(Occurrence, Institution)
        .join(Institution, Institution.id == Occurrence.institution_id)
        .where(Occurrence.business_date == d)
        .order_by(Occurrence.deadline_utc.nulls_last(), Institution.name)
    ).all()
    open_by_occ = {
        occ_id: (inc_id, prio)
        for occ_id, inc_id, prio in s.execute(
            select(Incident.occurrence_id, Incident.id, Incident.priority)
            .where(Incident.status != "RESOLVED", Incident.occurrence_id.is_not(None))
            .order_by(Incident.priority.desc())
        )
    }
    labels = _slot_labels(s)
    board = []
    for o, inst in rows:
        inc = open_by_occ.get(o.id)
        board.append(
            {
                "occurrence_id": str(o.id),
                "institution_id": str(inst.id),
                "institution": inst.name,
                "code": inst.code,
                "tier": inst.tier,
                "slot_key": o.slot_key,
                "slot_label": labels.get((inst.id, o.slot_key), "Takvim dışı teslimat"),
                "window_start": _minutes(o.window_start_utc),
                "deadline": _minutes(o.deadline_utc),
                "status": o.status,
                "first_received": _minutes(o.first_received_at),
                "max_severity": o.max_severity,
                "incident_id": str(inc[0]) if inc else None,
                "incident_priority": inc[1] if inc else None,
            }
        )
    status_counts = Counter(b["status"] for b in board)

    since30 = now - timedelta(days=30)
    due = s.execute(
        select(Occurrence.status, func.count())
        .where(Occurrence.expected.is_(True), Occurrence.deadline_utc.between(since30, now))
        .group_by(Occurrence.status)
    ).all()
    due_c: dict[str, int] = {st: n for st, n in due}
    due_total = sum(due_c.values())
    acked = s.execute(
        select(Incident.opened_at, Incident.acknowledged_at).where(
            Incident.opened_at >= since30, Incident.acknowledged_at.is_not(None)
        )
    ).all()
    resolved = s.execute(
        select(Incident.opened_at, Incident.resolved_at).where(
            Incident.opened_at >= since30, Incident.resolution.in_((*LABELLED, "DUPLICATE"))
        )
    ).all()
    from loadguard.services.governance import system_status

    return {
        "as_of": now.isoformat(),
        "system": system_status(s),
        "business_date": d.isoformat(),
        "open_incidents": {p: n for p, n in open_incs},
        "today": {
            "expected": sum(1 for b in board if b["status"] != "UNSCHEDULED"),
            "by_status": dict(status_counts),
        },
        "last_30_days": {
            "on_time_rate": round(due_c.get("RECEIVED", 0) / due_total, 4) if due_total else None,
            "late": due_c.get("LATE", 0),
            "missing": due_c.get("MISSING", 0),
            "deliveries": due_total,
            "median_minutes_to_acknowledge": _median_minutes([(a, b) for a, b in acked]),
            "median_minutes_to_resolve": _median_minutes([(a, b) for a, b in resolved]),
        },
        "board": board,
    }


def institutions_health(s: Session) -> list[dict[str, Any]]:
    now, d = clock.now(), today()
    since = now - timedelta(days=30)
    stats: dict[uuid.UUID, Counter[str]] = defaultdict(Counter)
    for inst_id, status, n in s.execute(
        select(Occurrence.institution_id, Occurrence.status, func.count())
        .where(Occurrence.expected.is_(True), Occurrence.deadline_utc.between(since, now))
        .group_by(Occurrence.institution_id, Occurrence.status)
    ):
        stats[inst_id][status] += n
    open_inc: dict[uuid.UUID | None, int] = {
        i: n
        for i, n in s.execute(
            select(Incident.institution_id, func.count())
            .where(Incident.status != "RESOLVED")
            .group_by(Incident.institution_id)
        )
    }
    last_load: dict[uuid.UUID, datetime] = {
        i: t
        for i, t in s.execute(
            select(Load.institution_id, func.max(Load.received_at)).group_by(Load.institution_id)
        )
    }
    today_status = {
        (i, k): st
        for i, k, st in s.execute(
            select(Occurrence.institution_id, Occurrence.slot_key, Occurrence.status).where(
                Occurrence.business_date == d
            )
        )
    }
    out = []
    for inst in s.scalars(select(Institution).order_by(Institution.tier, Institution.name)):
        c = stats.get(inst.id, Counter())
        total = sum(c.values())
        eff = effective_contract(s, inst.id, d)
        statuses = [st for (i, _), st in today_status.items() if i == inst.id]
        out.append(
            {
                "id": str(inst.id),
                "code": inst.code,
                "name": inst.name,
                "sector": inst.sector,
                "tier": inst.tier,
                "active": inst.active,
                "contract_version": eff[0].version if eff else None,
                "cadence": ", ".join(sl.label for sl in eff[1].slots) if eff else None,
                "on_time_rate_30d": round(c.get("RECEIVED", 0) / total, 4) if total else None,
                "late_30d": c.get("LATE", 0),
                "missing_30d": c.get("MISSING", 0),
                "open_incidents": open_inc.get(inst.id, 0),
                "last_delivery_at": last_load[inst.id].isoformat() if inst.id in last_load else None,
                "today": statuses,
            }
        )
    return out


def institution_series(s: Session, institution_id: uuid.UUID, metric: str, days: int) -> list[dict[str, Any]]:
    d = today()
    rows = s.scalars(
        select(Occurrence)
        .where(
            Occurrence.institution_id == institution_id,
            Occurrence.business_date >= d - timedelta(days=days),
            Occurrence.business_date <= d,
        )
        .order_by(Occurrence.business_date, Occurrence.slot_key)
    ).all()
    inc_occ = {
        o: (i, st, res)
        for o, i, st, res in s.execute(
            select(Incident.occurrence_id, Incident.id, Incident.status, Incident.resolution).where(
                Incident.institution_id == institution_id
            )
        )
    }
    out = []
    for o in rows:
        b = (o.baselines or {}).get(metric) or {}
        inc = inc_occ.get(o.id)
        out.append(
            {
                "occurrence_id": str(o.id),
                "date": o.business_date.isoformat(),
                "slot_key": o.slot_key,
                "status": o.status,
                "expected_slot": o.expected,
                "observed": o.metrics.get(metric) if o.metrics else None,
                "expected": b.get("expected"),
                "lower": b.get("lower"),
                "upper": b.get("upper"),
                "learning": b.get("status") == "LEARNING",
                "arrival": _minutes(o.first_received_at),
                "deadline": _minutes(o.deadline_utc),
                "window_start": _minutes(o.window_start_utc),
                "max_severity": o.max_severity,
                "excluded": o.excluded_from_baseline,
                "regime_break": o.regime_break,
                "incident_id": str(inc[0]) if inc else None,
                "incident_status": inc[1] if inc else None,
                "resolution": inc[2] if inc else None,
            }
        )
    return out


def insights(s: Session, days: int = 90) -> dict[str, Any]:
    since = clock.now() - timedelta(days=days)
    incs = s.execute(
        select(Incident, Institution.name)
        .outerjoin(Institution, Institution.id == Incident.institution_id)
        .where(Incident.opened_at >= since)
    ).all()
    by_code: dict[str, Counter[str]] = defaultdict(Counter)
    by_inst: dict[str, Counter[str]] = defaultdict(Counter)
    weekly: Counter[str] = Counter()
    for inc, name in incs:
        res = inc.resolution or ("OPEN" if inc.status != "RESOLVED" else "OTHER")
        for code in inc.codes:
            by_code[code][res] += 1
            by_code[code]["total"] += 1
        key = name or "Sistemik"
        by_inst[key][res] += 1
        by_inst[key]["total"] += 1
        wk = inc.opened_at.astimezone(ops_tz()).date()
        weekly[(wk - timedelta(days=wk.weekday())).isoformat()] += 1

    def precision(c: Counter[str]) -> float | None:
        tp = c.get("TRUE_POSITIVE", 0)
        fp = c.get("FALSE_POSITIVE", 0) + c.get("NEW_NORMAL", 0)
        return round(tp / (tp + fp), 3) if tp + fp else None

    return {
        "period_days": days,
        "total_incidents": len(incs),
        "by_code": sorted(
            ({"code": k, **dict(v), "precision": precision(v)} for k, v in by_code.items()),
            key=lambda r: -r["total"],
        ),
        "by_institution": sorted(
            ({"institution": k, **dict(v), "precision": precision(v)} for k, v in by_inst.items()),
            key=lambda r: -r["total"],
        ),
        "weekly_volume": [{"week": k, "count": weekly[k]} for k in sorted(weekly)],
        "auto_cleared": sum(1 for inc, _ in incs if inc.resolution == "AUTO_CLEARED"),
        "suppressed": sum(1 for inc, _ in incs if inc.resolution == "SUPPRESSED"),
    }


def simulation_quality(s: Session) -> dict[str, Any] | None:
    truths = s.scalars(select(SimTruth)).all()
    if not truths:
        return None
    occs = {
        (o.institution_id, o.slot_key, o.business_date): o
        for o in s.scalars(
            select(Occurrence).where(Occurrence.business_date >= min(t.business_date for t in truths))
        )
    }
    recall: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    truth_keys = set()
    for t in truths:
        truth_keys.add((t.institution_id, t.slot_key, t.business_date))
        if t.kind not in EXPECTED_CODES:
            continue
        o = occs.get((t.institution_id, t.slot_key, t.business_date))
        if o is None or o.evaluated_at is None:
            continue
        recall[t.kind][1] += 1
        if {f["code"] for f in o.findings} & EXPECTED_CODES[t.kind]:
            recall[t.kind][0] += 1
    alerts = [o for k, o in occs.items() if o.max_severity in ("WARNING", "CRITICAL") and o.evaluated_at]
    true_alerts = sum(1 for o in alerts if (o.institution_id, o.slot_key, o.business_date) in truth_keys)
    return {
        "note": "Sentetik veride enjekte edilen anomalilere göre ölçülmüştür (gerçek dünya performansı değildir).",
        "recall_by_kind": {k: {"caught": v[0], "total": v[1]} for k, v in sorted(recall.items())},
        "alerts": len(alerts),
        "precision": round(true_alerts / len(alerts), 3) if alerts else None,
    }


def contract_view(cv: ContractVersion) -> dict[str, Any]:
    spec = load_spec(cv.spec)
    return {
        "id": str(cv.id),
        "institution_id": str(cv.institution_id),
        "version": cv.version,
        "status": cv.status,
        "effective_from": cv.effective_from.isoformat(),
        "spec": spec.canonical(),
        "spec_hash": cv.spec_hash,
        "origin": cv.origin,
        "change_note": cv.change_note,
        "created_by": cv.created_by,
        "created_at": cv.created_at.isoformat() if cv.created_at else None,
        "submitted_at": cv.submitted_at.isoformat() if cv.submitted_at else None,
        "decided_by": cv.decided_by,
        "decided_at": cv.decided_at.isoformat() if cv.decided_at else None,
        "decision_note": cv.decision_note,
        "backtest": cv.backtest,
    }
