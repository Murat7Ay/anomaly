"""Worker process: drains the job queue and runs periodic ticks.

Any number of workers may run; jobs are claimed with SKIP LOCKED and the periodic tick is guarded by
a Postgres advisory lock, so exactly one worker sweeps deadlines at a time.

    python -m loadguard.worker.main
"""

from __future__ import annotations

import signal
import time
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, text

from loadguard.ai.briefing import generate_brief
from loadguard.core import clock
from loadguard.core.config import get_settings
from loadguard.core.logging import configure_logging, get_logger
from loadguard.db.models import SimPlannedLoad
from loadguard.db.session import unit_of_work
from loadguard.services import pipeline
from loadguard.services.analytics import today
from loadguard.services.common import claim_jobs, finish_job, requeue_stuck_jobs
from loadguard.services.governance import beat
from loadguard.services.notify import notify_incident

log = get_logger(__name__)
TICK_LOCK_ID = 7_340_001
_running = True


def handle_job(kind: str, payload: dict[str, Any]) -> None:
    with unit_of_work() as s:
        match kind:
            case "EVALUATE_LOAD":
                pipeline.process_load(s, uuid.UUID(payload["load_id"]))
            case "AI_BRIEF":
                generate_brief(s, uuid.UUID(payload["incident_id"]))
            case "NOTIFY":
                notify_incident(s, uuid.UUID(payload["incident_id"]))
            case _:
                raise ValueError(f"unknown job kind {kind}")


def run_jobs(batch: int = 20) -> int:
    with unit_of_work() as s:
        jobs = [(j.id, j.kind, dict(j.payload)) for j in claim_jobs(s, batch)]
    for job_id, kind, payload in jobs:
        err = None
        try:
            handle_job(kind, payload)
        except Exception as e:
            log.exception("job_failed", job_id=job_id, kind=kind)
            err = f"{type(e).__name__}: {e}"
        with unit_of_work() as s:
            finish_job(s, job_id, err)
    return len(jobs)


def ingest_planned_sim_loads() -> int:
    """Demo mode: synthetic deliveries 'arrive' when their simulated time comes."""
    with unit_of_work() as s:
        due = s.scalars(
            select(SimPlannedLoad)
            .where(SimPlannedLoad.ingested.is_(False), SimPlannedLoad.due_at <= clock.now())
            .order_by(SimPlannedLoad.due_at)
            .limit(200)
            .with_for_update(skip_locked=True)
        ).all()
        for p in due:
            pipeline.ingest(s, pipeline.LoadIn(**{**p.payload, "received_at": p.due_at}))
            p.ingested = True
        return len(due)


def tick() -> None:
    with unit_of_work() as s:
        beat(s, ticked=True)
    with unit_of_work() as s:
        got = s.scalar(text("select pg_try_advisory_xact_lock(:k)"), {"k": TICK_LOCK_ID})
        if not got:
            return
        requeue_stuck_jobs(s)
        d = today()
        pipeline.materialize(s, d)
        pipeline.materialize(s, d + timedelta(days=1))
    if get_settings().simulator_live:
        ingest_planned_sim_loads()
    with unit_of_work() as s:
        if s.scalar(text("select pg_try_advisory_xact_lock(:k)"), {"k": TICK_LOCK_ID}):
            n = pipeline.sweep(s)
            pipeline.systemic_check(s)
            if n:
                log.info("sweep", evaluated=n)


def main() -> None:
    st = get_settings()
    configure_logging(st.log_level, json=st.log_json)

    def stop(*_: object) -> None:
        global _running
        _running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    log.info("worker_started", ai_provider=st.ai_provider, simulator_live=st.simulator_live)
    last_tick = 0.0
    last_beat = 0.0
    while _running:
        try:
            if time.monotonic() - last_beat >= 10:
                with unit_of_work() as s:
                    beat(s)
                last_beat = time.monotonic()
            if time.monotonic() - last_tick >= st.worker_tick_seconds:
                tick()
                last_tick = time.monotonic()
            if run_jobs() == 0:
                time.sleep(st.worker_poll_seconds)
        except Exception:
            log.exception("worker_loop_error")
            time.sleep(5)
    log.info("worker_stopped")


if __name__ == "__main__":
    main()
