"""Labelled synthetic debt-load deliveries.

Each archetype encodes a realistic biller behaviour (cadence, arrival habits, month-start bill peaks,
weekday effects, heating-season amounts, growth, a tariff-driven level shift). Anomalies are injected
with ground-truth labels so detector quality can be *measured* (precision/recall), not eyeballed.
"""

from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from loadguard.domain.calendar import BusinessCalendar, MonthPhase
from loadguard.domain.contract import (
    Cadence,
    ContractSpec,
    DeliverySlot,
    Direction,
    HardLimit,
    HolidayShift,
    LimitMetric,
    MetricWatch,
    QualityPolicy,
    Sensitivity,
    Severity,
    WatchedMetric,
)
from loadguard.domain.model import LoadFacts
from loadguard.domain.schedule import ExpectedOccurrence, expected_occurrences, local_to_utc

ANOMALY_KINDS = {
    "MISSING": 0.17,
    "LATE": 0.17,
    "PARTIAL": 0.16,
    "SPIKE": 0.10,
    "UNIT_SCALE": 0.06,
    "DUPLICATE_FILE": 0.08,
    "STALE": 0.08,
    "ZERO_AMOUNTS": 0.08,
    "NEGATIVE": 0.05,
    "UNEXPECTED": 0.05,
    "SEGMENT_SHIFT": 0.06,  # a subscriber segment silently drops out; totals look roughly normal
}


@dataclass(frozen=True)
class Archetype:
    code: str
    name: str
    sector: str
    tier: int
    spec: ContractSpec
    records: float
    avg_amount: float
    arrival_mean: int  # local minutes
    arrival_sd: int
    noise: float = 0.06
    growth_per_year: float = 0.05
    month_start: float = 1.0
    weekday: dict[int, float] = field(default_factory=dict)
    heating: float = 0.0  # extra amount share in Dec-Feb
    level_shift: tuple[date, float] | None = None
    anomaly_rate: float = 0.03
    spiky: float = 0.0  # natural (benign) occasional volume bursts share; makes some billers noisy


@dataclass(frozen=True)
class SimLoad:
    institution_code: str
    facts: LoadFacts
    file_name: str
    slot_hint: str | None


@dataclass(frozen=True)
class Truth:
    institution_code: str
    slot_key: str
    business_date: date
    kind: str


def _t(h: int, m: int = 0) -> time:
    return time(h, m)


def _volume_spec(*slots: DeliverySlot, sens: Sensitivity = Sensitivity.MEDIUM, **kw: object) -> ContractSpec:
    return ContractSpec(
        slots=list(slots),
        metrics=[
            MetricWatch(metric=WatchedMetric.RECORD_COUNT, sensitivity=sens),
            MetricWatch(metric=WatchedMetric.TOTAL_AMOUNT, sensitivity=sens),
            MetricWatch(
                metric=WatchedMetric.CUSTOMER_COUNT, sensitivity=Sensitivity.LOW, direction=Direction.LOW_ONLY
            ),
        ],
        **kw,  # type: ignore[arg-type,unused-ignore]
    )


def _bd(key: str, label: str, ws: time, dl: time) -> DeliverySlot:
    return DeliverySlot(key=key, label=label, cadence=Cadence.BUSINESS_DAYS, window_start=ws, deadline=dl)


def _ed(key: str, label: str, ws: time, dl: time) -> DeliverySlot:
    return DeliverySlot(key=key, label=label, cadence=Cadence.EVERY_DAY, window_start=ws, deadline=dl)


def _wk(days: list[int], ws: time, dl: time) -> DeliverySlot:
    return DeliverySlot(
        key="weekly",
        label="Haftalık borç dosyası",
        cadence=Cadence.WEEKLY,
        weekdays=days,
        window_start=ws,
        deadline=dl,
    )


def _mo(days: list[int], ws: time, dl: time, last: bool = False) -> DeliverySlot:
    return DeliverySlot(
        key="monthly",
        label="Aylık fatura dosyası",
        cadence=Cadence.MONTHLY,
        month_days=days or None,
        last_business_day=last,
        holiday_shift=HolidayShift.NEXT_BUSINESS_DAY,
        window_start=ws,
        deadline=dl,
    )


def _limit_records(mx: float) -> list[HardLimit]:
    return [
        HardLimit(
            id="max-records",
            metric=LimitMetric.RECORD_COUNT,
            max=mx,
            severity=Severity.CRITICAL,
            note="Sistem kapasite sınırı",
        )
    ]


def default_archetypes() -> list[Archetype]:
    bd, ed, wk, mo, limit_records = _bd, _ed, _wk, _mo, _limit_records
    return [
        Archetype(
            "ELK01",
            "Anadolu Elektrik Dağıtım A.Ş.",
            "ELECTRICITY",
            1,
            _volume_spec(bd("daily", "Günlük borç dosyası", _t(6), _t(10)), limits=limit_records(2_000_000)),
            records=210_000,
            avg_amount=640,
            arrival_mean=7 * 60 + 30,
            arrival_sd=18,
            month_start=1.55,
            weekday={1: 1.12, 5: 0.93},
            heating=0.18,
            growth_per_year=0.07,
        ),
        Archetype(
            "ELK02",
            "Ege Elektrik Perakende Satış",
            "ELECTRICITY",
            1,
            _volume_spec(bd("daily", "Günlük borç dosyası", _t(6), _t(9, 30))),
            records=145_000,
            avg_amount=590,
            arrival_mean=7 * 60 + 5,
            arrival_sd=12,
            month_start=1.4,
            weekday={1: 1.08},
            heating=0.15,
        ),
        Archetype(
            "ELK03",
            "Trakya Enerji Dağıtım",
            "ELECTRICITY",
            2,
            _volume_spec(bd("daily", "Günlük borç dosyası", _t(6, 30), _t(11))),
            records=62_000,
            avg_amount=610,
            arrival_mean=8 * 60 + 20,
            arrival_sd=35,
            month_start=1.5,
            heating=0.12,
            level_shift=(date(2026, 4, 1), 1.28),
        ),
        Archetype(
            "GAZ01",
            "Kuzey Doğalgaz Dağıtım",
            "GAS",
            1,
            _volume_spec(bd("daily", "Günlük borç dosyası", _t(6), _t(10))),
            records=120_000,
            avg_amount=820,
            arrival_mean=7 * 60 + 45,
            arrival_sd=20,
            month_start=1.3,
            heating=0.9,
            noise=0.07,
        ),
        Archetype(
            "GAZ02",
            "Orta Anadolu Gaz",
            "GAS",
            2,
            _volume_spec(bd("daily", "Günlük borç dosyası", _t(7), _t(12)), sens=Sensitivity.HIGH),
            records=38_000,
            avg_amount=760,
            arrival_mean=9 * 60 + 10,
            arrival_sd=40,
            heating=0.8,
            noise=0.10,
            spiky=0.04,
        ),
        Archetype(
            "SU01",
            "Metropol Su ve Kanalizasyon İdaresi",
            "WATER",
            1,
            _volume_spec(mo([5, 20], _t(8), _t(14))),
            records=480_000,
            avg_amount=310,
            arrival_mean=10 * 60,
            arrival_sd=45,
            noise=0.05,
        ),
        Archetype(
            "SU02",
            "Yeşilvadi Belediyesi Su İşleri",
            "WATER",
            3,
            _volume_spec(mo([10], _t(9), _t(16))),
            records=21_000,
            avg_amount=270,
            arrival_mean=11 * 60 + 30,
            arrival_sd=70,
            noise=0.08,
        ),
        Archetype(
            "SU03",
            "Kıyıkent Su Kanal Müdürlüğü",
            "WATER",
            3,
            _volume_spec(mo([], _t(9), _t(17), last=True)),
            records=15_500,
            avg_amount=240,
            arrival_mean=13 * 60,
            arrival_sd=60,
            noise=0.09,
        ),
        Archetype(
            "TEL01",
            "Atlas Telekom",
            "TELECOM",
            1,
            _volume_spec(ed("daily", "Günlük fatura borç dosyası", _t(4), _t(7))),
            records=330_000,
            avg_amount=410,
            arrival_mean=5 * 60 + 10,
            arrival_sd=10,
            weekday={6: 0.7, 7: 0.6},
            month_start=1.25,
            growth_per_year=0.04,
        ),
        Archetype(
            "TEL02",
            "Vega Mobil İletişim",
            "TELECOM",
            1,
            _volume_spec(ed("daily", "Günlük fatura borç dosyası", _t(4), _t(8))),
            records=270_000,
            avg_amount=380,
            arrival_mean=5 * 60 + 40,
            arrival_sd=15,
            weekday={6: 0.75, 7: 0.65},
            month_start=1.2,
        ),
        Archetype(
            "NET01",
            "Nova İnternet Hizmetleri",
            "TELECOM",
            2,
            _volume_spec(wk([1, 4], _t(8), _t(13))),
            records=56_000,
            avg_amount=330,
            arrival_mean=9 * 60 + 30,
            arrival_sd=30,
            weekday={1: 1.15},
        ),
        Archetype(
            "NET02",
            "Fiberyol Genişbant",
            "TELECOM",
            3,
            _volume_spec(wk([3], _t(9), _t(15)), quality=QualityPolicy(unexpected_delivery="WARNING")),
            records=9_800,
            avg_amount=290,
            arrival_mean=11 * 60,
            arrival_sd=50,
            noise=0.09,
            anomaly_rate=0.05,
        ),
        Archetype(
            "TV01",
            "Yıldız Dijital Yayın",
            "MEDIA",
            3,
            _volume_spec(mo([1], _t(8), _t(15))),
            records=44_000,
            avg_amount=210,
            arrival_mean=9 * 60 + 40,
            arrival_sd=25,
        ),
        Archetype(
            "EGT01",
            "Bilge Koleji Eğitim Kurumları",
            "EDUCATION",
            3,
            _volume_spec(mo([1, 15], _t(9), _t(17))),
            records=4_200,
            avg_amount=6_800,
            arrival_mean=12 * 60,
            arrival_sd=90,
            noise=0.04,
        ),
        Archetype(
            "SGK01",
            "Kamu Prim Tahsilat Merkezi",
            "PUBLIC",
            1,
            _volume_spec(bd("daily", "Günlük prim borç dosyası", _t(5), _t(8, 30))),
            records=520_000,
            avg_amount=1_450,
            arrival_mean=6 * 60 + 40,
            arrival_sd=12,
            month_start=1.8,
            noise=0.04,
        ),
        Archetype(
            "BLD01",
            "Merkez Büyükşehir Belediyesi Emlak Vergisi",
            "PUBLIC",
            2,
            _volume_spec(bd("daily", "Günlük vergi borç dosyası", _t(7), _t(12)), sens=Sensitivity.HIGH),
            records=88_000,
            avg_amount=1_150,
            arrival_mean=9 * 60,
            arrival_sd=55,
            noise=0.12,
            spiky=0.06,
        ),
        Archetype(
            "SIG01",
            "Güvence Sigorta Prim Tahsilat",
            "INSURANCE",
            2,
            _volume_spec(bd("daily", "Günlük prim dosyası", _t(8), _t(13))),
            records=27_000,
            avg_amount=980,
            arrival_mean=10 * 60 + 15,
            arrival_sd=35,
            month_start=1.35,
        ),
        Archetype(
            "ISI01",
            "Bölgesel Isıtma Kooperatifi",
            "HEATING",
            3,
            _volume_spec(wk([2], _t(9), _t(16))),
            records=7_400,
            avg_amount=1_250,
            arrival_mean=10 * 60 + 30,
            arrival_sd=45,
            heating=1.4,
            noise=0.08,
        ),
    ]


def _arrival(rng: random.Random, a: Archetype, slot: DeliverySlot) -> int:
    lo = slot.window_start.hour * 60 + slot.window_start.minute
    hi = slot.deadline.hour * 60 + slot.deadline.minute - 5
    m = int(rng.gauss(a.arrival_mean, a.arrival_sd))
    return max(lo - 15, min(hi, m))


def _volume(
    a: Archetype, cal: BusinessCalendar, d: date, rng: random.Random, epoch: date
) -> tuple[float, float]:
    years = (d - epoch).days / 365.0
    f = (1 + a.growth_per_year) ** years
    if cal.month_phase(d) == MonthPhase.START:
        f *= a.month_start
    f *= a.weekday.get(d.isoweekday(), 1.0)
    if a.level_shift and d >= a.level_shift[0]:
        f *= a.level_shift[1]
    if a.spiky and rng.random() < a.spiky:
        f *= rng.uniform(
            1.25, 1.6
        )  # benign bursts (campaign billing, catch-up runs): realistic false-alarm bait
    f *= math.exp(rng.gauss(0, a.noise))
    month_heat = {12: 1.0, 1: 1.0, 2: 0.85, 11: 0.5, 3: 0.4}.get(d.month, 0.0)
    amount_f = (1 + a.heating * month_heat) * math.exp(rng.gauss(0, a.noise / 3))
    return a.records * f, a.avg_amount * amount_f


def _hash(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def simulate_institution(
    a: Archetype,
    cal: BusinessCalendar,
    start: date,
    end: date,
    *,
    seed: int,
    outage_days: set[date] | None = None,
    forced: dict[date, str] | None = None,
) -> tuple[list[SimLoad], list[Truth]]:
    rng = random.Random(f"{seed}:{a.code}")
    outage_days = outage_days or set()
    loads: list[SimLoad] = []
    truths: list[Truth] = []
    prev: LoadFacts | None = None
    tz = a.spec.timezone
    seq = 0

    def mk(
        d: date, minutes: int, records: float, avg: float, *, slot: str | None, **over: object
    ) -> LoadFacts:
        nonlocal seq
        seq += 1
        r = max(int(records), 0)
        ts = local_to_utc(d, time(0, 0), tz) + timedelta(minutes=minutes, seconds=rng.randint(0, 59))
        base = dict(
            id=f"{a.code}-{d:%Y%m%d}-{seq}",
            received_at=ts,
            content_hash=_hash(a.code, d, r, seq),
            record_count=r,
            total_amount=round(r * avg, 2),
            customer_count=int(r * rng.uniform(0.93, 0.97)),
            zero_amount_count=int(r * rng.uniform(0.002, 0.012)),
            negative_amount_count=0,
            duplicate_record_count=int(r * rng.uniform(0, 0.002)),
            max_amount=round(avg * rng.uniform(25, 60), 2),
        )
        base.update(over)
        return LoadFacts(**base)  # type: ignore[arg-type]

    occs: list[ExpectedOccurrence] = expected_occurrences(a.spec, cal, start, end)
    if a.level_shift and start <= a.level_shift[0] <= end:
        first_after = next((o for o in occs if o.business_date >= a.level_shift[0]), None)
        if first_after:
            truths.append(Truth(a.code, first_after.slot_key, first_after.business_date, "LEVEL_SHIFT"))
    expected_days = {o.business_date for o in occs}

    for o in occs:
        slot = a.spec.slot(o.slot_key)
        assert slot is not None
        d = o.business_date
        records, avg = _volume(a, cal, d, rng, start)
        minutes = _arrival(rng, a, slot)
        deadline_min = slot.deadline.hour * 60 + slot.deadline.minute

        if d in outage_days and deadline_min <= 11 * 60:
            truths.append(Truth(a.code, o.slot_key, d, "SYSTEMIC_OUTAGE"))
            minutes = 11 * 60 + 40 + rng.randint(0, 50)  # platform recovered late morning; files flow in
            lf = mk(d, minutes, records, avg, slot=o.slot_key)
            loads.append(SimLoad(a.code, lf, f"{a.code}_{d:%Y%m%d}.txt", o.slot_key))
            prev = lf
            continue

        kind = None
        if forced and d in forced and prev is not None:
            kind = forced[d]
        elif rng.random() < a.anomaly_rate and prev is not None:
            kind = rng.choices(list(ANOMALY_KINDS), weights=list(ANOMALY_KINDS.values()))[0]
            if kind == "UNEXPECTED" and slot.cadence in (Cadence.BUSINESS_DAYS, Cadence.EVERY_DAY):
                kind = "SPIKE"

        if kind == "MISSING":
            truths.append(Truth(a.code, o.slot_key, d, kind))
            continue
        if kind == "LATE":
            minutes = deadline_min + rng.randint(25, 300)
        if kind == "SPIKE":
            records *= rng.uniform(1.4, 3.2)
        if kind == "PARTIAL":
            share = rng.uniform(0.2, 0.75)
            heal = rng.random() < 0.4
            lf = mk(d, minutes, records * share, avg, slot=o.slot_key)
            loads.append(SimLoad(a.code, lf, f"{a.code}_{d:%Y%m%d}_part1.txt", o.slot_key))
            if heal:
                lf2 = mk(d, minutes + rng.randint(30, 120), records * (1 - share), avg, slot=o.slot_key)
                loads.append(SimLoad(a.code, lf2, f"{a.code}_{d:%Y%m%d}_part2.txt", o.slot_key))
            truths.append(Truth(a.code, o.slot_key, d, "PARTIAL_HEALED" if heal else "PARTIAL"))
            prev = lf
            continue

        over: dict[str, object] = {}
        if kind == "UNIT_SCALE":
            avg *= 100
        elif kind == "ZERO_AMOUNTS":
            over["zero_amount_count"] = int(records * rng.uniform(0.18, 0.4))
        elif kind == "NEGATIVE":
            over["negative_amount_count"] = rng.randint(3, 250)
        elif kind == "SEGMENT_SHIFT":
            over["customer_count"] = int(records * rng.uniform(0.93, 0.97) * rng.uniform(0.62, 0.8))
        lf = mk(d, minutes, records, avg, slot=o.slot_key, **over)
        if kind == "DUPLICATE_FILE" and prev is not None:
            lf = LoadFacts(**{**prev.__dict__, "id": lf.id, "received_at": lf.received_at})
        elif kind == "STALE" and prev is not None:
            lf = LoadFacts(
                **{
                    **prev.__dict__,
                    "id": lf.id,
                    "received_at": lf.received_at,
                    "content_hash": lf.content_hash,
                }
            )
        if kind and kind != "UNEXPECTED":
            truths.append(Truth(a.code, o.slot_key, d, kind))
        loads.append(SimLoad(a.code, lf, f"{a.code}_{d:%Y%m%d}.txt", o.slot_key))
        prev = lf

        if kind == "UNEXPECTED":
            # an extra delivery on a day nothing is expected
            nd = d + timedelta(days=1)
            while nd in expected_days or not cal.is_business_day(nd):
                nd += timedelta(days=1)
            if nd <= end:
                extra = mk(nd, minutes, records * 0.3, avg, slot=None)
                loads.append(SimLoad(a.code, extra, f"{a.code}_{nd:%Y%m%d}_extra.txt", None))
                truths.append(Truth(a.code, "__unscheduled__", nd, "UNEXPECTED"))

    loads.sort(key=lambda s: s.facts.received_at)
    return loads, truths


def pick_outage_days(cal: BusinessCalendar, start: date, end: date, seed: int, n: int = 2) -> set[date]:
    rng = random.Random(f"outage:{seed}")
    days = [start + timedelta(days=i) for i in range(30, (end - start).days - 3)]
    days = [d for d in days if cal.is_business_day(d)]
    return set(rng.sample(days, min(n, len(days))))


def now_utc() -> datetime:
    return datetime.now(UTC)
