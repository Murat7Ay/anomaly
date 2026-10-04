"""What would this contract change have done? Compared against the current contract and analyst verdicts.

Governance: a contract draft is never approved blind. The approver sees alert volume, which confirmed
incidents would still be caught, and which known false alarms would disappear.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from loadguard.domain.calendar import BusinessCalendar
from loadguard.domain.contract import ContractSpec, Severity
from loadguard.domain.model import LoadFacts
from loadguard.domain.replay import ReplayOccurrence, replay


@dataclass(frozen=True)
class Verdict:
    slot_key: str
    business_date: date
    category: str
    resolution: str  # TRUE_POSITIVE | FALSE_POSITIVE | EXPECTED_EVENT | NEW_NORMAL


def _alerts(occs: list[ReplayOccurrence]) -> dict[tuple[str, date], set[tuple[str, str]]]:
    out: dict[tuple[str, date], set[tuple[str, str]]] = {}
    for o in occs:
        assert o.result is not None
        fs = {
            (f.category.value, f.code) for f in o.result.findings if f.severity.rank >= Severity.WARNING.rank
        }
        if fs:
            out[(o.slot_key, o.business_date)] = fs
    return out


def _summary(alerts: dict[tuple[str, date], set[tuple[str, str]]]) -> dict[str, Any]:
    codes = Counter(code for fs in alerts.values() for _, code in fs)
    return {"alerting_occurrences": len(alerts), "by_code": dict(codes.most_common())}


def run_backtest(
    *,
    candidate: ContractSpec,
    current: ContractSpec | None,
    calendar: BusinessCalendar,
    loads: list[LoadFacts],
    start: date,
    end: date,
    now: datetime,
    history_labels: dict[tuple[str, date], str],
    verdicts: list[Verdict],
) -> dict[str, Any]:
    cand = _alerts(
        replay(
            spec_for=lambda _d: candidate,
            calendar=calendar,
            loads=loads,
            start=start,
            end=end,
            now=now,
            labels=history_labels,
        )
    )
    cur = (
        _alerts(
            replay(
                spec_for=lambda _d: current,
                calendar=calendar,
                loads=loads,
                start=start,
                end=end,
                now=now,
                labels=history_labels,
            )
        )
        if current is not None
        else {}
    )

    def caught(alerts: dict[tuple[str, date], set[tuple[str, str]]], v: Verdict) -> bool:
        return any(cat == v.category for cat, _ in alerts.get((v.slot_key, v.business_date), set()))

    in_range = [v for v in verdicts if start <= v.business_date <= end]
    tps = [v for v in in_range if v.resolution == "TRUE_POSITIVE"]
    fps = [v for v in in_range if v.resolution in ("FALSE_POSITIVE", "NEW_NORMAL")]

    changes = []
    for key in sorted(set(cand) | set(cur), key=lambda k: (k[1], k[0])):
        a = sorted(c for _, c in cur.get(key, set()))
        b = sorted(c for _, c in cand.get(key, set()))
        if a != b:
            changes.append(
                {"slot_key": key[0], "business_date": key[1].isoformat(), "current": a, "candidate": b}
            )

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1},
        "candidate": _summary(cand),
        "current": _summary(cur) if current is not None else None,
        "verdicts": {
            "true_positive_total": len(tps),
            "caught_by_candidate": sum(caught(cand, v) for v in tps),
            "caught_by_current": sum(caught(cur, v) for v in tps) if current is not None else None,
            "false_alarm_total": len(fps),
            "false_alarms_remaining_candidate": sum(caught(cand, v) for v in fps),
            "false_alarms_remaining_current": sum(caught(cur, v) for v in fps)
            if current is not None
            else None,
        },
        "changes": changes[:100],
        "changes_total": len(changes),
    }
