"""Long-term trust: decision reproducibility, shadow models, liveness of the monitor itself, metrics."""

from __future__ import annotations

import os
import socket
import uuid
from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from loadguard import __version__
from loadguard.core import clock
from loadguard.core.config import get_settings
from loadguard.core.errors import NotFound
from loadguard.db.models import (
    AiInteraction,
    Evaluation,
    Incident,
    InputSnapshot,
    Institution,
    Job,
    Occurrence,
    ShadowResult,
    SimTruth,
    WorkerHeartbeat,
)
from loadguard.domain import snapshot as snap
from loadguard.domain.engine import ENGINE_VERSION

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


# --- decision reproducibility ------------------------------------------------------------------------


def evaluation_dossier(s: Session, evaluation_id: uuid.UUID) -> dict[str, Any]:
    ev = s.get(Evaluation, evaluation_id)
    if ev is None:
        raise NotFound("Değerlendirme bulunamadı")
    row = s.get(InputSnapshot, ev.snapshot_sha) if ev.snapshot_sha else None
    payload = row.payload if row else None
    return {
        "id": str(ev.id),
        "occurrence_id": str(ev.occurrence_id),
        "trigger": ev.trigger,
        "evaluated_at": ev.evaluated_at.isoformat(),
        "engine_version": ev.engine_version,
        "spec_hash": ev.spec_hash,
        "snapshot_sha256": ev.snapshot_sha,
        "inputs": payload,
        "result": ev.result,
    }


def verify_evaluation(s: Session, evaluation_id: uuid.UUID) -> dict[str, Any]:
    ev = s.get(Evaluation, evaluation_id)
    if ev is None:
        raise NotFound("Değerlendirme bulunamadı")
    if ev.snapshot_sha is None:
        return {"evaluation_id": str(ev.id), "verifiable": False, "reason": "no_snapshot (backfilled record)"}
    row = s.get(InputSnapshot, ev.snapshot_sha)
    assert row is not None
    integrity = snap.fingerprint(row.payload) == ev.snapshot_sha
    out = snap.verify(row.payload, ev.result)
    return {
        "evaluation_id": str(ev.id),
        "verifiable": True,
        "snapshot_integrity": integrity,
        "recorded_engine": ev.engine_version,
        "current_engine": ENGINE_VERSION,
        **out,
    }


def verify_sample(s: Session, n: int = 200) -> dict[str, Any]:
    """Re-run a random sample of recorded decisions with the current engine.

    Before an engine upgrade: mismatches are the behavioural change the upgrade introduces.
    After an infrastructure change (new Python/numpy): mismatches mean non-determinism. Both must be explained.
    """
    ids = list(
        s.scalars(
            select(Evaluation.id).where(Evaluation.snapshot_sha.is_not(None)).order_by(func.random()).limit(n)
        )
    )
    results = [verify_evaluation(s, i) for i in ids]
    mismatches = [r for r in results if not r.get("reproduced") or not r.get("snapshot_integrity")]
    return {
        "checked": len(results),
        "reproduced": len(results) - len(mismatches),
        "engine": ENGINE_VERSION,
        "mismatches": mismatches[:20],
    }


# --- shadow models ------------------------------------------------------------------------------------

LABELLED_TRUE = ("TRUE_POSITIVE",)
LABELLED_FALSE = ("FALSE_POSITIVE", "NEW_NORMAL")


def shadow_report(s: Session, days: int = 120) -> list[dict[str, Any]]:
    since = clock.now() - timedelta(days=days)
    rows = s.execute(
        select(ShadowResult, Occurrence, Institution.name)
        .join(Occurrence, Occurrence.id == ShadowResult.occurrence_id)
        .join(Institution, Institution.id == Occurrence.institution_id)
        .where(ShadowResult.evaluated_at >= since)
    ).all()
    verdicts: dict[uuid.UUID, set[str]] = defaultdict(set)
    for occ_id, res in s.execute(
        select(Incident.occurrence_id, Incident.resolution).where(Incident.resolution.is_not(None))
    ):
        if occ_id:
            verdicts[occ_id].add(res)
    truths = {(t.institution_id, t.slot_key, t.business_date) for t in s.scalars(select(SimTruth))}

    by: dict[str, dict[str, Any]] = {}
    for sr, occ, name in rows:
        rep = by.setdefault(
            sr.challenger,
            {
                "challenger": sr.challenger,
                "evaluated": 0,
                "agreement": Counter(),
                "verdicts": Counter(),
                "only_challenger": [],
                "truth": Counter(),
            },
        )
        rep["evaluated"] += 1
        champ = {f["code"] for f in occ.findings if f["severity"] in ("WARNING", "CRITICAL")}
        chall = set(sr.codes)
        key = (
            "both"
            if champ and chall
            else "champion_only"
            if champ
            else "challenger_only"
            if chall
            else "neither"
        )
        rep["agreement"][key] += 1
        v = verdicts.get(occ.id, set())
        if v & set(LABELLED_TRUE):
            rep["verdicts"]["confirmed_issues"] += 1
            rep["verdicts"]["confirmed_caught_by_challenger"] += bool(chall)
        if v & set(LABELLED_FALSE):
            rep["verdicts"]["false_alarms"] += 1
            rep["verdicts"]["false_alarms_challenger_still_alerts"] += bool(chall)
        if truths:
            is_true = (occ.institution_id, occ.slot_key, occ.business_date) in truths
            if chall:
                rep["truth"]["challenger_alerts"] += 1
                rep["truth"]["challenger_true"] += is_true
            if champ:
                rep["truth"]["champion_alerts"] += 1
                rep["truth"]["champion_true"] += is_true
            if is_true:
                rep["truth"]["issues"] += 1
                rep["truth"]["champion_caught"] += bool(champ)
                rep["truth"]["challenger_caught"] += bool(chall)
        if key == "challenger_only" and len(rep["only_challenger"]) < 25:
            rep["only_challenger"].append(
                {
                    "occurrence_id": str(occ.id),
                    "institution_id": str(occ.institution_id),
                    "institution": name,
                    "business_date": occ.business_date.isoformat(),
                    "codes": sorted(chall - champ) or sorted(chall),
                }
            )
    out = []
    for rep in by.values():
        rep["agreement"] = dict(rep["agreement"])
        rep["verdicts"] = dict(rep["verdicts"])
        rep["truth"] = dict(rep["truth"]) or None
        rep["only_challenger"].sort(key=lambda x: x["business_date"], reverse=True)
        out.append(rep)
    return sorted(out, key=lambda r: r["challenger"])


# --- liveness of the monitor itself -------------------------------------------------------------------


def beat(s: Session, *, ticked: bool = False) -> None:
    now = clock.now()
    values: dict[str, Any] = {
        "worker_id": WORKER_ID,
        "started_at": now,
        "last_beat_at": now,
        "version": __version__,
    }
    update: dict[str, Any] = {"last_beat_at": now, "version": __version__}
    if ticked:
        values["last_tick_at"] = now
        update["last_tick_at"] = now
    s.execute(
        insert(WorkerHeartbeat)
        .values(**values)
        .on_conflict_do_update(index_elements=["worker_id"], set_=update)
    )
    # forget workers that have been gone for a day
    s.query(WorkerHeartbeat).filter(WorkerHeartbeat.last_beat_at < now - timedelta(days=1)).delete()


def local_worker_alive(s: Session) -> bool:
    """Container healthcheck: has a worker *in this container* (same hostname) beaten recently?"""
    host = socket.gethostname()
    last = s.scalar(
        select(func.max(WorkerHeartbeat.last_beat_at)).where(WorkerHeartbeat.worker_id.like(f"{host}:%"))
    )
    return (
        last is not None and (clock.now() - last).total_seconds() <= get_settings().worker_stale_after_seconds
    )


def system_status(s: Session) -> dict[str, Any]:
    now = clock.now()
    st = get_settings()
    last_beat = s.scalar(select(func.max(WorkerHeartbeat.last_beat_at)))
    last_tick = s.scalar(select(func.max(WorkerHeartbeat.last_tick_at)))
    queued = s.scalar(select(func.count()).select_from(Job).where(Job.status == "QUEUED")) or 0
    oldest = s.scalar(select(func.min(Job.run_at)).where(Job.status == "QUEUED", Job.run_at <= now))
    failed = (
        s.scalar(
            select(func.count())
            .select_from(Job)
            .where(Job.status == "FAILED", Job.finished_at >= now - timedelta(days=1))
        )
        or 0
    )
    beat_age = (now - last_beat).total_seconds() if last_beat else None
    worker_ok = beat_age is not None and beat_age <= st.worker_stale_after_seconds
    return {
        "healthy": bool(worker_ok and failed == 0),
        "worker": {
            "alive": worker_ok,
            "last_beat_age_seconds": round(beat_age) if beat_age is not None else None,
            "last_tick_age_seconds": round((now - last_tick).total_seconds()) if last_tick else None,
            "instances": s.scalar(
                select(func.count())
                .select_from(WorkerHeartbeat)
                .where(WorkerHeartbeat.last_beat_at >= now - timedelta(seconds=st.worker_stale_after_seconds))
            ),
        },
        "queue": {
            "queued": queued,
            "oldest_ready_age_seconds": round((now - oldest).total_seconds()) if oldest else 0,
            "failed_24h": failed,
        },
        "engine_version": ENGINE_VERSION,
        "app_version": __version__,
        "shadow_challengers": st.shadow_list(),
    }


def prometheus_metrics(s: Session) -> str:
    """Prometheus text exposition. Computed from the database, so it is correct across processes."""
    st = system_status(s)
    lines: list[str] = []

    def g(name: str, help_: str, samples: list[tuple[dict[str, str], float]]) -> None:
        lines.append(f"# HELP {name} {help_}")
        lines.append(f"# TYPE {name} gauge")
        for labels, v in samples:
            lab = ",".join(f'{k}="{val}"' for k, val in labels.items())
            lines.append(f"{name}{{{lab}}} {v}" if lab else f"{name} {v}")

    g("loadguard_worker_alive", "1 if a worker heartbeat is fresh", [({}, int(st["worker"]["alive"]))])
    g(
        "loadguard_worker_heartbeat_age_seconds",
        "Age of the newest worker heartbeat",
        [
            (
                {},
                st["worker"]["last_beat_age_seconds"]
                if st["worker"]["last_beat_age_seconds"] is not None
                else -1,
            )
        ],
    )
    g("loadguard_jobs_queued", "Jobs waiting", [({}, st["queue"]["queued"])])
    g(
        "loadguard_jobs_oldest_ready_age_seconds",
        "Age of the oldest runnable job",
        [({}, st["queue"]["oldest_ready_age_seconds"])],
    )
    g(
        "loadguard_jobs_failed_24h",
        "Jobs that exhausted retries in the last 24h",
        [({}, st["queue"]["failed_24h"])],
    )
    open_by = s.execute(
        select(Incident.priority, func.count())
        .where(Incident.status != "RESOLVED")
        .group_by(Incident.priority)
    ).all()
    g("loadguard_incidents_open", "Open incidents by priority", [({"priority": p}, n) for p, n in open_by])
    occ_today = s.execute(
        select(Occurrence.status, func.count())
        .where(Occurrence.evaluated_at >= clock.now() - timedelta(hours=24))
        .group_by(Occurrence.status)
    ).all()
    g(
        "loadguard_occurrences_evaluated_24h",
        "Occurrences evaluated in 24h by status",
        [({"status": k}, n) for k, n in occ_today],
    )
    ai = s.execute(
        select(AiInteraction.status, func.count())
        .where(AiInteraction.at >= clock.now() - timedelta(hours=24))
        .group_by(AiInteraction.status)
    ).all()
    g("loadguard_ai_calls_24h", "Advisory AI calls in 24h by status", [({"status": k}, n) for k, n in ai])
    lines.append(f'loadguard_build_info{{engine="{ENGINE_VERSION}",app="{__version__}"}} 1')
    return "\n".join(lines) + "\n"
