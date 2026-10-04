"""Small shared service helpers: calendar loading, audit trail, job queue."""

from __future__ import annotations

import time as _time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from loadguard.core import clock
from loadguard.db.models import AuditLog, Holiday, Job
from loadguard.domain.calendar import BusinessCalendar

_CAL_CACHE: dict[str, tuple[float, BusinessCalendar]] = {}
_CAL_TTL_S = 300.0


def get_calendar(s: Session, code: str = "TR") -> BusinessCalendar:
    hit = _CAL_CACHE.get(code)
    if hit and _time.monotonic() - hit[0] < _CAL_TTL_S:
        return hit[1]
    rows = s.scalars(select(Holiday).where(Holiday.calendar_code == code)).all()
    cal = BusinessCalendar(
        code=code,
        holidays=frozenset(r.day for r in rows if not r.half_day),
        half_days=frozenset(r.day for r in rows if r.half_day),
    )
    _CAL_CACHE[code] = (_time.monotonic(), cal)
    return cal


def clear_calendar_cache() -> None:
    _CAL_CACHE.clear()


def audit(s: Session, actor: str, action: str, entity_type: str, entity_id: object, **details: Any) -> None:
    s.add(
        AuditLog(
            at=clock.now(),
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details,
        )
    )


# --- job queue (Postgres, FOR UPDATE SKIP LOCKED) -------------------------------------------------

MAX_ATTEMPTS = 5


def enqueue(
    s: Session,
    kind: str,
    payload: dict[str, Any],
    *,
    run_at: datetime | None = None,
    dedupe_key: str | None = None,
) -> None:
    stmt = insert(Job).values(
        kind=kind,
        payload=payload,
        run_at=run_at or clock.now(),
        status="QUEUED",
        attempts=0,
        dedupe_key=dedupe_key,
    )
    s.execute(stmt.on_conflict_do_nothing(index_elements=["dedupe_key"]) if dedupe_key else stmt)


def claim_jobs(s: Session, limit: int = 10) -> list[Job]:
    jobs = list(
        s.scalars(
            select(Job)
            .where(Job.status == "QUEUED", Job.run_at <= clock.now())
            .order_by(Job.run_at, Job.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
    )
    for j in jobs:
        j.status = "RUNNING"
        j.attempts += 1
        j.locked_at = clock.now()
    return jobs


def finish_job(s: Session, job_id: int, error: str | None = None) -> None:
    job = s.get(Job, job_id)
    if job is None:
        return
    if error is None:
        job.status, job.finished_at, job.dedupe_key = "DONE", clock.now(), None
    elif job.attempts >= MAX_ATTEMPTS:
        job.status, job.last_error, job.finished_at, job.dedupe_key = (
            "FAILED",
            error[:4000],
            clock.now(),
            None,
        )
    else:
        job.status, job.last_error = "QUEUED", error[:4000]
        job.run_at = clock.now() + timedelta(seconds=10 * 2**job.attempts)


def requeue_stuck_jobs(s: Session, older_than: timedelta = timedelta(minutes=10)) -> None:
    """Jobs left RUNNING by a crashed worker become runnable again (at-least-once semantics)."""
    s.execute(
        update(Job)
        .where(Job.status == "RUNNING", Job.locked_at < clock.now() - older_than)
        .values(status="QUEUED")
    )
