"""Infer a delivery contract from observed history (onboarding / contract review).

Deterministic statistics, not an LLM: cadence from calendar coverage, arrival window from empirical
quantiles. The output is a *suggestion* that becomes a draft only after a human saves it, and is
active only after a different human approves it.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

import numpy as np

from loadguard.domain.calendar import BusinessCalendar
from loadguard.domain.contract import (
    Cadence,
    ContractSpec,
    DeliverySlot,
    MetricWatch,
    Sensitivity,
    WatchedMetric,
)
from loadguard.domain.fmt import hhmm, pct
from loadguard.domain.schedule import local_date, local_minutes

WEEKDAY_TR = {1: "Pazartesi", 2: "Salı", 3: "Çarşamba", 4: "Perşembe", 5: "Cuma", 6: "Cumartesi", 7: "Pazar"}


@dataclass(frozen=True)
class InferredContract:
    spec: ContractSpec | None
    confidence: float
    rationale: list[str]


def _round_down(m: float, step: int = 30) -> int:
    return int(math.floor(m / step) * step)


def _round_up(m: float, step: int = 30) -> int:
    return int(math.ceil(m / step) * step)


def _t(minutes: int) -> time:
    minutes = max(0, min(minutes, 23 * 60 + 59))
    return time(minutes // 60, minutes % 60)


def infer_contract(
    arrivals: list[datetime], cal: BusinessCalendar, *, tz: str = "Europe/Istanbul", start: date, end: date
) -> InferredContract:
    why: list[str] = []
    by_day: dict[date, int] = {}
    for ts in sorted(arrivals):
        d = local_date(ts, tz)
        if start <= d <= end and d not in by_day:
            by_day[d] = local_minutes(ts, tz)
    if len(by_day) < 8:
        return InferredContract(None, 0.0, ["Öneri için en az 8 teslim günü gerekir."])

    all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    bdays = [d for d in all_days if cal.is_business_day(d)]
    wdays = [d for d in all_days if not cal.is_business_day(d)]
    delivered = set(by_day)
    bd_cov = len(delivered & set(bdays)) / max(len(bdays), 1)
    we_cov = len(delivered & set(wdays)) / max(len(wdays), 1)

    slot: DeliverySlot
    explained: set[date]
    mins = np.array(list(by_day.values()), dtype=float)
    ws = _t(_round_down(float(np.quantile(mins, 0.03))) - 30)
    dl = _t(min(_round_up(float(np.quantile(mins, 0.99))) + 60, 23 * 60 + 30))
    common = {"window_start": ws, "deadline": dl, "grace_minutes": 0}

    if bd_cov >= 0.85:
        cadence = Cadence.EVERY_DAY if we_cov >= 0.85 else Cadence.BUSINESS_DAYS
        slot = DeliverySlot(key="daily", label="Günlük borç dosyası", cadence=cadence, **common)
        explained = delivered if cadence == Cadence.EVERY_DAY else delivered & set(bdays)
        why.append(
            f"İş günlerinin {pct(bd_cov)}'inde, tatil/hafta sonu günlerinin {pct(we_cov)}'inde teslimat var → "
            + ("her gün" if cadence == Cadence.EVERY_DAY else "iş günleri")
            + " teslimatı."
        )
    else:
        wd_cov = {}
        for wd in range(1, 8):
            days = [d for d in all_days if d.isoweekday() == wd]
            wd_cov[wd] = len(delivered & set(days)) / max(len(days), 1)
        weekly_days = [wd for wd, c in wd_cov.items() if c >= 0.7]
        weekly_share = sum(1 for d in delivered if d.isoweekday() in weekly_days) / len(delivered)
        if weekly_days and weekly_share >= 0.8:
            slot = DeliverySlot(
                key="weekly",
                label="Haftalık borç dosyası",
                cadence=Cadence.WEEKLY,
                weekdays=weekly_days,
                **common,
            )
            explained = {d for d in delivered if d.isoweekday() in weekly_days}
            why.append(
                "Teslimatların "
                + pct(weekly_share)
                + "'i "
                + ", ".join(WEEKDAY_TR[w] for w in weekly_days)
                + " günlerinde → haftalık."
            )
        else:
            months = {(d.year, d.month) for d in all_days}
            last_bd = sum(1 for d in delivered if d == cal.last_business_day_of_month(d.year, d.month))
            # A shifted delivery (holiday -> next business day) is attributed to its nominal day if within 3 days.
            dom: Counter[int] = Counter()
            for d in delivered:
                dom[d.day] += 1
            peaks = sorted(day for day, c in dom.items() if c >= 0.5 * len(months))
            for day in list(peaks):
                for nd in range(day + 1, day + 4):
                    if nd in peaks:
                        peaks.remove(nd)
            use_last = last_bd >= 0.6 * len(months)
            if not peaks and not use_last:
                return InferredContract(
                    None,
                    0.0,
                    ["Teslimat günleri düzenli bir örüntü göstermiyor; sözleşme elle tanımlanmalı."],
                )
            slot = DeliverySlot(
                key="monthly",
                label="Aylık borç dosyası",
                cadence=Cadence.MONTHLY,
                month_days=peaks or None,
                last_business_day=use_last,
                **common,
            )
            explained = {
                d
                for d in delivered
                if any(0 <= d.day - p <= 3 for p in peaks)
                or (use_last and d == cal.last_business_day_of_month(d.year, d.month))
            }
            parts = [f"ayın {', '.join(map(str, peaks))}. günü"] if peaks else []
            if use_last:
                parts.append("ayın son iş günü")
            why.append(f"{len(months)} ayda teslimatlar {' ve '.join(parts)} etrafında yoğunlaşıyor → aylık.")

    why.append(
        f"Varış saatleri: medyan {hhmm(float(np.median(mins)))}, %99 {hhmm(float(np.quantile(mins, 0.99)))} → "
        f"pencere {ws:%H:%M}, son teslim {dl:%H:%M} (1 saat tampon)."
    )
    confidence = len(explained) / len(delivered)
    why.append(f"Önerilen takvim geçmiş teslimatların {pct(confidence)}'ini açıklıyor.")
    spec = ContractSpec(
        slots=[slot],
        metrics=[
            MetricWatch(metric=WatchedMetric.RECORD_COUNT, sensitivity=Sensitivity.MEDIUM),
            MetricWatch(metric=WatchedMetric.TOTAL_AMOUNT, sensitivity=Sensitivity.MEDIUM),
            MetricWatch(metric=WatchedMetric.CUSTOMER_COUNT, sensitivity=Sensitivity.LOW),
        ],
        timezone=tz,
    )
    return InferredContract(spec, round(confidence, 3), why)
