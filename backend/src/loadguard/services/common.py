"""Small shared service helpers: calendar loading, audit trail, job queue."""

from __future__ import annotations

import hashlib
import json
import time as _time
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from loadguard.core import clock
from loadguard.core.config import get_settings
from loadguard.db.models import AuditLog, Holiday, Job
from loadguard.domain.calendar import BusinessCalendar

_CAL_CACHE: dict[str, tuple[float, BusinessCalendar]] = {}
_CAL_TTL_S = 300.0


def get_calendar(s: Session, code: str | None = None) -> BusinessCalendar:
    code = code or get_settings().default_calendar
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


AUDIT_CHAIN_LOCK = 7_340_002


def audit_row_hash(
    prev: str | None, at: datetime, actor: str, action: str, entity_type: str, entity_id: str, details: Any
) -> str:
    """Stable forever: changing this breaks verification of every historical row. Version it instead."""
    body = json.dumps(
        {
            "at": at.astimezone(UTC).isoformat(),
            "actor": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "details": details,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(f"{prev or ''}|{body}".encode()).hexdigest()


def audit(s: Session, actor: str, action: str, entity_type: str, entity_id: object, **details: Any) -> None:
    """Append a tamper-evident audit row (each row commits to the previous row's hash)."""
    s.execute(text("select pg_advisory_xact_lock(:k)"), {"k": AUDIT_CHAIN_LOCK})  # serialise chain appends
    prev = s.scalar(select(AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1))
    at = clock.now()
    details = json.loads(json.dumps(details, default=str))  # exactly what JSONB will return
    row = AuditLog(
        at=at,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        details=details,
        prev_hash=prev,
        row_hash=audit_row_hash(prev, at, actor, action, entity_type, str(entity_id), details),
    )
    s.add(row)
    s.flush()


def verify_audit_chain(s: Session) -> dict[str, Any]:
    prev: str | None = None
    n = 0
    for row in s.scalars(select(AuditLog).order_by(AuditLog.id)).yield_per(1000):
        n += 1
        expected = audit_row_hash(
            prev, row.at, row.actor, row.action, row.entity_type, row.entity_id, row.details
        )
        if row.prev_hash != prev or row.row_hash != expected:
            return {"ok": False, "rows_checked": n, "first_broken_id": row.id}
        prev = row.row_hash
    return {"ok": True, "rows_checked": n, "head": prev}


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
