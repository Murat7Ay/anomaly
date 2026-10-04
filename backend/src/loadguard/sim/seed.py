"""Demo seed: users, holidays, institutions, contracts and ~16 months of labelled synthetic history.

History is evaluated with the same pure engine (replay) the live system uses, then persisted. Older
incidents get simulated analyst verdicts from ground truth so learning, tuning and quality pages have
real data. Today is left to the live worker (optionally with the live simulator).

    python -m loadguard.sim.seed [--days 480] [--reset]
"""

from __future__ import annotations

import argparse
import random
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from loadguard.core import clock
from loadguard.core.logging import configure_logging, get_logger
from loadguard.db.models import (
    ContractVersion,
    Evaluation,
    Holiday,
    Incident,
    IncidentEvent,
    Institution,
    Load,
    Occurrence,
    SimPlannedLoad,
    SimTruth,
    Suppression,
    User,
)
from loadguard.db.session import unit_of_work
from loadguard.domain.contract import Sensitivity, Severity
from loadguard.domain.holidays_tr import tr_calendar, tr_holidays
from loadguard.domain.model import Category
from loadguard.domain.replay import Label, replay
from loadguard.domain.triage import estimate_impact, priority_for
from loadguard.services.common import enqueue
from loadguard.services.contracts import backtest as run_contract_backtest
from loadguard.services.incidents import CODE_ORDER, CODE_TITLES
from loadguard.sim.simulator import default_archetypes, pick_outage_days, simulate_institution

log = get_logger(__name__)
TZ = ZoneInfo("Europe/Istanbul")
SEED = 2026
BENIGN = {"PARTIAL_HEALED", "LEVEL_SHIFT"}
OPEN_DAYS = 6  # incidents newer than this stay open for the demo

USERS = [
    ("ayse.yilmaz", "Ayşe Yılmaz", "ANALYST"),
    ("can.demir", "Can Demir", "ANALYST"),
    ("mehmet.kaya", "Mehmet Kaya", "APPROVER"),
    ("zeynep.arslan", "Zeynep Arslan", "ADMIN"),
]


def reset(s) -> None:  # type: ignore[no-untyped-def]
    s.execute(
        text(
            "TRUNCATE incident_events, notifications, incidents, evaluations, loads, occurrences, contract_versions, "
            "sim_planned_loads, sim_truths, suppressions, ai_interactions, jobs, audit_log, institutions, holidays, users "
            "RESTART IDENTITY CASCADE"
        )
    )


def seed(days: int = 480, *, do_reset: bool = False) -> None:
    rng = random.Random(SEED)
    now = clock.now()
    today = now.astimezone(TZ).date()
    start = today - timedelta(days=days)
    cal = tr_calendar()
    outages = pick_outage_days(cal, today - timedelta(days=200), today - timedelta(days=OPEN_DAYS + 1), SEED)

    with unit_of_work() as s:
        if do_reset:
            reset(s)
        if s.scalar(select(Institution.id).limit(1)):
            log.info("seed_skipped", reason="data already present (use --reset)")
            return
        s.add_all(User(username=u, display_name=n, role=r, email=f"{u}@example.local") for u, n, r in USERS)
        s.add_all(Holiday(calendar_code="TR", day=d, name=n, half_day=h) for d, n, h in tr_holidays())

    recent: list[date] = []
    d = today - timedelta(days=1)
    while len(recent) < 3:
        if cal.is_business_day(d):
            recent.append(d)
        d -= timedelta(days=1)
    yesterday = today - timedelta(days=1)
    # A fixed, recognisable demo scenario on the last business days (on top of random history).
    scenario: dict[str, dict[date, str]] = {
        "ELK02": {recent[0]: "PARTIAL"},
        "SGK01": {recent[0]: "UNIT_SCALE"},
        "ELK03": {recent[0]: "MISSING"},
        "SIG01": {recent[0]: "ZERO_AMOUNTS"},
        "GAZ01": {recent[1]: "LATE"},
        "BLD01": {recent[1]: "SPIKE"},
        "TEL01": {yesterday: "STALE"},
        "TEL02": {recent[2]: "DUPLICATE_FILE"},
    }
    for a in default_archetypes():
        _seed_institution(a, cal, start, today, now, outages, rng, scenario.get(a.code))

    with unit_of_work() as s:
        _demo_extras(s, now, today)
        from loadguard.services.pipeline import materialize

        materialize(
            s, today
        )  # the board shows today's expectations immediately, before the first worker tick
    log.info("seed_done", institutions=len(default_archetypes()), start=start.isoformat())


def _seed_institution(a, cal, start, today, now, outages, rng, forced=None) -> None:  # type: ignore[no-untyped-def]
    sim_loads, truths = simulate_institution(
        a, cal, start, today + timedelta(days=2), seed=SEED, outage_days=outages, forced=forced
    )
    yesterday_end = datetime.combine(today, time(0, 0), tzinfo=TZ)

    with unit_of_work() as s:
        inst = Institution(
            code=a.code,
            name=a.name,
            sector=a.sector,
            tier=a.tier,
            contact_email=f"entegrasyon@{a.code.lower()}.example",
        )
        s.add(inst)
        s.flush()
        cv = ContractVersion(
            institution_id=inst.id,
            version=1,
            status="APPROVED",
            effective_from=start,
            spec=a.spec.canonical(),
            spec_hash=a.spec.spec_hash(),
            origin="SEED",
            change_note="İlk sözleşme (kurum ile mutabakat)",
            created_by="zeynep.arslan",
            decided_by="mehmet.kaya",
            decided_at=now - timedelta(days=days_between(start, today)),
            submitted_at=now - timedelta(days=days_between(start, today)),
        )
        s.add(cv)
        s.flush()

        truth_by_occ: dict[tuple[str, date], list[str]] = defaultdict(list)
        for t in truths:
            if t.business_date < today:
                truth_by_occ[(t.slot_key, t.business_date)].append(t.kind)
                s.add(
                    SimTruth(
                        institution_id=inst.id,
                        slot_key=t.slot_key,
                        business_date=t.business_date,
                        kind=t.kind,
                    )
                )
        labels = {
            k: (Label.REGIME if "LEVEL_SHIFT" in v else Label.EXCLUDE)
            for k, v in truth_by_occ.items()
            if k[1] < today - timedelta(days=OPEN_DAYS) and not set(v) <= {"PARTIAL_HEALED"}
        }

        # Persist loads: history (<= now) as Load rows, future ones as planned for the live simulator.
        load_rows: dict[str, Load] = {}
        facts_hist = []
        for sl in sim_loads:
            f = sl.facts
            payload = dict(
                institution_code=a.code,
                external_id=f.id,
                content_hash=f.content_hash,
                record_count=f.record_count,
                total_amount=f.total_amount,
                customer_count=f.customer_count,
                zero_amount_count=f.zero_amount_count,
                negative_amount_count=f.negative_amount_count,
                duplicate_record_count=f.duplicate_record_count,
                max_amount=f.max_amount,
                file_name=sl.file_name,
                slot_hint=sl.slot_hint,
                source="SIM",
            )
            if f.received_at > now:
                s.add(SimPlannedLoad(institution_code=a.code, due_at=f.received_at, payload=payload))
                continue
            row = Load(
                id=uuid.uuid4(),
                institution_id=inst.id,
                external_id=f.id,
                received_at=f.received_at,
                source="SIM",
                file_name=sl.file_name,
                content_hash=f.content_hash,
                slot_hint=sl.slot_hint,
                record_count=f.record_count,
                total_amount=Decimal(str(f.total_amount)),
                customer_count=f.customer_count,
                zero_amount_count=f.zero_amount_count,
                negative_amount_count=f.negative_amount_count,
                duplicate_record_count=f.duplicate_record_count,
                max_amount=Decimal(str(f.max_amount)) if f.max_amount is not None else None,
            )
            s.add(row)
            load_rows[f.id] = row
            if f.received_at < yesterday_end:
                facts_hist.append(f)
            else:  # today's arrivals so far go through the live pipeline
                enqueue(s, "EVALUATE_LOAD", {"load_id": str(row.id)}, dedupe_key=f"load:{row.id}")
        s.flush()

        results = replay(
            spec_for=lambda _d: a.spec,
            calendar=cal,
            loads=facts_hist,
            start=start,
            end=today - timedelta(days=1),
            now=yesterday_end,
            labels=labels,
            slot_hints={sl.facts.id: sl.slot_hint for sl in sim_loads if sl.slot_hint},
        )
        persisted = []
        for ro in results:
            r = ro.result
            assert r is not None
            occ = Occurrence(
                id=uuid.uuid4(),
                institution_id=inst.id,
                slot_key=ro.slot_key,
                business_date=ro.business_date,
                expected=ro.expected is not None,
                window_start_utc=ro.expected.window_start_utc if ro.expected else None,
                deadline_utc=ro.expected.deadline_utc if ro.expected else None,
                status=r.status.value,
                first_received_at=ro.loads[0].received_at if ro.loads else None,
                load_count=len(ro.loads),
                metrics=r.metrics,
                baselines=r.baselines,
                findings=[f.to_dict() for f in r.findings],
                max_severity=r.max_severity,
                contract_version_id=cv.id,
                spec_hash=cv.spec_hash,
                evaluated_at=yesterday_end,
                excluded_from_baseline=labels.get((ro.slot_key, ro.business_date)) == Label.EXCLUDE,
                regime_break=labels.get((ro.slot_key, ro.business_date)) == Label.REGIME,
            )
            s.add(occ)
            persisted.append((ro, occ))
        s.flush()  # occurrences must exist before rows referencing them (no ORM relationships here)
        for ro, occ in persisted:
            r = ro.result
            assert r is not None
            for lf in ro.loads:
                load_rows[lf.id].occurrence_id = occ.id
                load_rows[lf.id].assignment_reason = "BACKFILL"
            s.add(
                Evaluation(
                    occurrence_id=occ.id,
                    trigger="BACKFILL",
                    evaluated_at=yesterday_end,
                    engine_version=r.engine_version,
                    contract_version_id=cv.id,
                    spec_hash=cv.spec_hash,
                    inputs={"load_ids": [lf.id for lf in ro.loads]},
                    result={"status": r.status.value, "findings": [f.to_dict() for f in r.findings]},
                )
            )
            if ro.business_date >= today - timedelta(days=150):
                _incidents_for(
                    s, inst, occ, r, a.spec, truth_by_occ.get((ro.slot_key, ro.business_date), []), today, rng
                )
        s.flush()
        log.info("seeded_institution", code=a.code, loads=len(load_rows), occurrences=len(results))


def days_between(a: date, b: date) -> int:
    return (b - a).days


def _incidents_for(s, inst, occ, r, spec, truth_kinds, today, rng) -> None:  # type: ignore[no-untyped-def]
    by_cat: dict[str, list] = defaultdict(list)  # type: ignore[type-arg]
    for f in r.findings:
        if f.severity.rank >= Severity.WARNING.rank:
            by_cat[f.category.value].append(f)
    slot = spec.slot(occ.slot_key)
    label = slot.label if slot else "Takvim dışı teslimat"
    real = [k for k in truth_kinds if k not in BENIGN]
    for cat, fs in by_cat.items():
        sev = max(fs, key=lambda f: f.severity.rank).severity
        impact = estimate_impact(fs, r.metrics, r.baselines.get("reference") or {})
        prio = priority_for(sev, inst.tier, impact)
        codes = sorted({f.code for f in fs})
        opened = (
            occ.deadline_utc
            if (cat == Category.TIMELINESS.value and occ.deadline_utc)
            else (occ.first_received_at or datetime.combine(occ.business_date, time(9), tzinfo=TZ))
        )
        what = ", ".join(CODE_TITLES.get(c, c) for c in sorted(codes, key=CODE_ORDER.index))
        inc = Incident(
            kind="OCCURRENCE",
            institution_id=inst.id,
            occurrence_id=occ.id,
            fingerprint=f"{occ.id}:{cat}",
            category=cat,
            codes=codes,
            title=f"{inst.name} — {label}: {what} ({occ.business_date:%d.%m.%Y})",
            status="OPEN",
            severity=sev.value,
            priority=prio.value,
            impact_customers=impact.customers,
            impact_amount=impact.amount,
            opened_at=opened,
            updated_at=opened,
        )
        s.add(inc)
        s.flush()
        s.add(
            IncidentEvent(
                incident_id=inc.id,
                at=opened,
                actor="system",
                kind="OPENED",
                message=" | ".join(f.message for f in fs),
                data={"codes": codes},
            )
        )
        recent = occ.business_date >= today - timedelta(days=OPEN_DAYS)
        analyst = rng.choice(["ayse.yilmaz", "can.demir"])
        if recent:
            if rng.random() < 0.35:
                inc.status, inc.acknowledged_at, inc.acknowledged_by, inc.assignee = (
                    "ACKNOWLEDGED",
                    opened + timedelta(minutes=rng.randint(4, 40)),
                    analyst,
                    analyst,
                )
                s.add(
                    IncidentEvent(
                        incident_id=inc.id,
                        at=inc.acknowledged_at,
                        actor=analyst,
                        kind="ACKNOWLEDGED",
                        message=f"{analyst} olayı üstlendi.",
                    )
                )
            continue
        ack = opened + timedelta(minutes=rng.randint(3, 55))
        done = ack + timedelta(minutes=rng.randint(15, 240))
        if "LEVEL_SHIFT" in truth_kinds and cat == "VOLUME":
            resolution, note = "NEW_NORMAL", "Kurum tarife güncellemesi yaptığını teyit etti; kalıcı artış."
        elif real:
            resolution, note = "TRUE_POSITIVE", f"Kurumla teyit edildi ({', '.join(real).lower()})."
        else:
            resolution, note = "FALSE_POSITIVE", "Kurum teyidi: olağan dalgalanma, aksiyon gerekmedi."
        inc.status, inc.acknowledged_at, inc.acknowledged_by, inc.assignee = "RESOLVED", ack, analyst, analyst
        inc.resolved_at, inc.resolved_by, inc.resolution, inc.resolution_note, inc.updated_at = (
            done,
            analyst,
            resolution,
            note,
            done,
        )
        s.add(
            IncidentEvent(
                incident_id=inc.id,
                at=ack,
                actor=analyst,
                kind="ACKNOWLEDGED",
                message=f"{analyst} olayı üstlendi.",
            )
        )
        s.add(
            IncidentEvent(
                incident_id=inc.id,
                at=done,
                actor=analyst,
                kind="RESOLVED",
                message=f"Karar: {resolution} — {note}",
                data={"resolution": resolution},
            )
        )


def _demo_extras(s, now: datetime, today: date) -> None:  # type: ignore[no-untyped-def]
    # A pending four-eyes approval with a real backtest: relax the noisy biller's sensitivity.
    inst = s.scalars(select(Institution).where(Institution.code == "BLD01")).one()
    cur = s.scalars(select(ContractVersion).where(ContractVersion.institution_id == inst.id)).one()
    from loadguard.domain.contract import ContractSpec

    spec = ContractSpec.model_validate(cur.spec)
    relaxed = spec.model_copy(
        update={
            "metrics": [
                m.model_copy(update={"sensitivity": Sensitivity.MEDIUM})
                if m.sensitivity == Sensitivity.HIGH
                else m
                for m in spec.metrics
            ]
        }
    )
    cv = ContractVersion(
        institution_id=inst.id,
        version=2,
        status="PENDING_APPROVAL",
        effective_from=today + timedelta(days=1),
        spec=relaxed.canonical(),
        spec_hash=relaxed.spec_hash(),
        origin="TUNING",
        change_note="Son 3 ayda hacim uyarılarının çoğu yanlış alarm; hassasiyeti HIGH → MEDIUM düşürme önerisi.",
        created_by="ayse.yilmaz",
        submitted_at=now - timedelta(hours=3),
    )
    s.add(cv)
    s.flush()
    cv.backtest = run_contract_backtest(s, inst.id, relaxed)

    # Planned maintenance announced by a biller (findings recorded, nobody paged).
    su = s.scalars(select(Institution).where(Institution.code == "SU02")).one()
    s.add(
        Suppression(
            institution_id=su.id,
            starts_at=now + timedelta(days=3),
            ends_at=now + timedelta(days=4),
            reason="Kurum duyurusu: faturalama sistemi göçü nedeniyle dosya gönderimi yapılmayacak.",
            created_by="mehmet.kaya",
        )
    )


def main() -> None:
    configure_logging("INFO")
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=480)
    p.add_argument("--reset", action="store_true")
    args = p.parse_args()
    seed(args.days, do_reset=args.reset)


if __name__ == "__main__":
    main()
