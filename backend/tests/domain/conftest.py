from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from loadguard.domain.calendar import BusinessCalendar
from loadguard.domain.contract import Cadence, ContractSpec, DeliverySlot, MetricWatch, WatchedMetric
from loadguard.domain.holidays_tr import tr_calendar
from loadguard.domain.model import LoadFacts

TZ = ZoneInfo("Europe/Istanbul")


@pytest.fixture(scope="session")
def cal() -> BusinessCalendar:
    return tr_calendar()


@pytest.fixture
def daily_spec() -> ContractSpec:
    return ContractSpec(
        slots=[
            DeliverySlot(
                key="daily",
                label="Günlük",
                cadence=Cadence.BUSINESS_DAYS,
                window_start=time(6),
                deadline=time(10),
            )
        ],
        metrics=[
            MetricWatch(metric=WatchedMetric.RECORD_COUNT),
            MetricWatch(metric=WatchedMetric.TOTAL_AMOUNT),
        ],
    )


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return datetime.combine(d, time(hh, mm), tzinfo=TZ).astimezone(UTC)


_seq = iter(range(1, 10**9))


def load(
    d: date, hh: int, mm: int = 0, *, records: int = 100_000, avg: float = 500.0, **kw: object
) -> LoadFacts:
    n = next(_seq)
    base: dict[str, object] = dict(
        id=f"L{n}",
        received_at=at(d, hh, mm),
        content_hash=f"h{n}",
        record_count=records,
        total_amount=records * avg,
        customer_count=int(records * 0.95),
        zero_amount_count=int(records * 0.005),
    )
    base.update(kw)
    return LoadFacts(**base)  # type: ignore[arg-type]


def business_days(cal: BusinessCalendar, start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if cal.is_business_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out
