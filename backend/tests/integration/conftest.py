"""Integration tests run against a real PostgreSQL (the production datastore), never a SQLite stand-in."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import pytest

TEST_DB = os.environ.get(
    "LOADGUARD_TEST_DATABASE_URL", "postgresql+psycopg://loadguard:loadguard@127.0.0.1:55432/loadguard_test"
)
os.environ["LG_DATABASE_URL"] = TEST_DB
os.environ["LG_AI_PROVIDER"] = "none"

from sqlalchemy import text  # noqa: E402

from loadguard.core import clock  # noqa: E402
from loadguard.core.config import get_settings  # noqa: E402
from loadguard.db.models import Base, ContractVersion, Holiday, Institution, User  # noqa: E402
from loadguard.db.session import engine, unit_of_work  # noqa: E402
from loadguard.domain.contract import (  # noqa: E402
    Cadence,
    ContractSpec,
    DeliverySlot,
    MetricWatch,
    WatchedMetric,
)
from loadguard.domain.holidays_tr import tr_holidays  # noqa: E402
from loadguard.services import pipeline  # noqa: E402
from loadguard.services.common import clear_calendar_cache  # noqa: E402

TZ = ZoneInfo("Europe/Istanbul")
TARGET = date(2026, 9, 16)  # Wednesday


def _ensure_database() -> None:
    raw = TEST_DB.replace("postgresql+psycopg://", "postgresql://")
    base, name = raw.rsplit("/", 1)
    try:
        with psycopg.connect(f"{base}/postgres", autocommit=True, connect_timeout=3) as c:
            if not c.execute("select 1 from pg_database where datname=%s", (name,)).fetchone():
                c.execute(f'create database "{name}"')
    except psycopg.OperationalError as e:
        pytest.skip(f"PostgreSQL not reachable for integration tests: {e}")


@pytest.fixture(scope="session", autouse=True)
def database() -> Iterator[None]:
    _ensure_database()
    get_settings.cache_clear()
    engine.cache_clear()
    # Run the real migrations (not create_all): triggers and data migrations are part of what we test.
    from alembic import command
    from alembic.config import Config

    with engine().begin() as c:
        c.execute(text("drop schema public cascade; create schema public"))
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield
    engine().dispose()


SPEC = ContractSpec(
    slots=[
        DeliverySlot(
            key="daily",
            label="Günlük borç dosyası",
            cadence=Cadence.BUSINESS_DAYS,
            window_start=time(6),
            deadline=time(10),
        )
    ],
    metrics=[MetricWatch(metric=WatchedMetric.RECORD_COUNT), MetricWatch(metric=WatchedMetric.TOTAL_AMOUNT)],
)


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=TZ).astimezone(UTC)


def set_now(ts: datetime) -> None:
    clock.set_clock(lambda: ts)


def make_institution(code: str, tier: int = 1, *, history_days: int = 40) -> None:
    """Institution + approved contract + clean history processed through the *live* pipeline."""
    with unit_of_work() as s:
        inst = Institution(code=code, name=f"Kurum {code}", sector="ELECTRICITY", tier=tier)
        s.add(inst)
        s.flush()
        s.add(
            ContractVersion(
                institution_id=inst.id,
                version=1,
                status="APPROVED",
                effective_from=date(2025, 1, 1),
                spec=SPEC.canonical(),
                spec_hash=SPEC.spec_hash(),
                created_by="seed",
                decided_by="seed2",
            )
        )
    d, n = TARGET - timedelta(days=history_days * 2), 0
    from loadguard.domain.holidays_tr import tr_calendar

    cal = tr_calendar()
    while d < TARGET:
        if cal.is_business_day(d):
            n += 1
            ingest(code, d, 7, 30 + n % 20, records=100_000 + (n % 5) * 1000, ext=f"{code}-hist-{d}")
            if n >= history_days:
                pass
        d += timedelta(days=1)


def ingest(
    code: str,
    d: date,
    hh: int,
    mm: int,
    *,
    records: int = 100_000,
    ext: str | None = None,
    avg: float = 500.0,
    content_hash: str | None = None,
) -> None:
    ts = at(d, hh, mm)
    set_now(ts)
    with unit_of_work() as s:
        load, created = pipeline.ingest(
            s,
            pipeline.LoadIn(
                institution_code=code,
                external_id=ext or f"{code}-{d}-{hh}{mm}-{records}",
                received_at=ts,
                content_hash=content_hash or f"{code}{d}{hh}{mm}{records}",
                record_count=records,
                total_amount=records * avg,
                customer_count=int(records * 0.95),
            ),
        )
        load_id = load.id
    if created:
        with unit_of_work() as s:
            pipeline.process_load(s, load_id)


def sweep_at(ts: datetime) -> None:
    set_now(ts)
    with unit_of_work() as s:
        pipeline.sweep(s)
        pipeline.systemic_check(s)


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    with engine().begin() as c:
        tables = ", ".join(
            t.name for t in Base.metadata.sorted_tables
        )  # TRUNCATE is allowed; UPDATE/DELETE are not
        c.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    clear_calendar_cache()
    with unit_of_work() as s:
        s.add_all(
            [
                User(username="ayse", display_name="Ayşe", role="ANALYST"),
                User(username="mehmet", display_name="Mehmet", role="APPROVER"),
            ]
        )
        s.add_all(Holiday(calendar_code="TR", day=d, name=n, half_day=h) for d, n, h in tr_holidays())
    yield
    clock.reset_clock()
