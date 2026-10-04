"""Measure detector quality on labelled simulations.

    python -m loadguard.sim.evaluate --days 300 --seed 7

Prints recall per injected anomaly kind, alert precision and false-alert rate. The same function backs
a regression test so a detector change that silently degrades quality fails CI.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from loadguard.domain.contract import Severity
from loadguard.domain.holidays_tr import tr_calendar
from loadguard.domain.replay import Label, replay
from loadguard.sim.simulator import Archetype, default_archetypes, pick_outage_days, simulate_institution

EXPECTED_CODE = {
    "MISSING": {"MISSING_DELIVERY"},
    "LATE": {"LATE_DELIVERY"},
    "PARTIAL": {"VOLUME_LOW"},
    "SPIKE": {"VOLUME_HIGH", "LIMIT_BREACH"},
    "UNIT_SCALE": {"UNIT_SCALE_SUSPECT"},
    "DUPLICATE_FILE": {"DUPLICATE_FILE"},
    "STALE": {"STALE_DATA"},
    "ZERO_AMOUNTS": {"ZERO_AMOUNT_RECORDS"},
    "NEGATIVE": {"NEGATIVE_AMOUNTS"},
    "UNEXPECTED": {"UNEXPECTED_DELIVERY"},
    "SYSTEMIC_OUTAGE": {"LATE_DELIVERY"},
}
BENIGN = {"LEVEL_SHIFT", "PARTIAL_HEALED"}


@dataclass
class QualityReport:
    occurrences: int
    alerts: int
    true_alerts: int
    recall: dict[str, tuple[int, int]]  # kind -> (caught, total)
    healed_partials_still_alerting: int
    false_alerts_by_code: dict[str, int]

    @property
    def precision(self) -> float:
        return self.true_alerts / self.alerts if self.alerts else 1.0

    @property
    def false_alerts_per_100(self) -> float:
        return 100 * (self.alerts - self.true_alerts) / max(self.occurrences, 1)

    def overall_recall(self) -> float:
        caught = sum(c for c, _ in self.recall.values())
        total = sum(t for _, t in self.recall.values())
        return caught / total if total else 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "occurrences": self.occurrences,
            "alerts": self.alerts,
            "precision": round(self.precision, 3),
            "overall_recall": round(self.overall_recall(), 3),
            "false_alerts_per_100_occurrences": round(self.false_alerts_per_100, 2),
            "recall_by_kind": {k: {"caught": c, "total": t} for k, (c, t) in sorted(self.recall.items())},
            "false_alerts_by_code": self.false_alerts_by_code,
            "healed_partials_still_alerting": self.healed_partials_still_alerting,
        }


def evaluate_quality(
    *, days: int = 480, seed: int = 7, archetypes: list[Archetype] | None = None, use_labels: bool = True
) -> QualityReport:
    cal = tr_calendar()
    end = date(2026, 9, 30)
    start = end - timedelta(days=days)
    now = datetime.combine(end + timedelta(days=1), time(23, 59), tzinfo=UTC)
    outages = pick_outage_days(cal, start, end, seed)
    archetypes = archetypes or default_archetypes()

    occ_n = alerts = true_alerts = healed_alerting = 0
    recall: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    false_codes: Counter[str] = Counter()
    warmup = 60  # baselines need history; score only after warm-up

    for a in archetypes:
        sim_loads, truths = simulate_institution(a, cal, start, end, seed=seed, outage_days=outages)
        truth_by_occ: dict[tuple[str, date], list[str]] = defaultdict(list)
        for t in truths:
            truth_by_occ[(t.slot_key, t.business_date)].append(t.kind)
        labels: dict[tuple[str, date], str] = {}
        if use_labels:
            for key, kinds in truth_by_occ.items():
                labels[key] = Label.REGIME if "LEVEL_SHIFT" in kinds else Label.EXCLUDE
        results = replay(
            spec_for=lambda _d, s=a.spec: s,  # type: ignore[misc]
            calendar=cal,
            loads=[s.facts for s in sim_loads],
            start=start + timedelta(days=warmup),
            end=end,
            now=now,
            labels=labels,
            slot_hints={s.facts.id: s.slot_hint for s in sim_loads if s.slot_hint},
        )
        for occ in results:
            assert occ.result is not None
            occ_n += 1
            kinds = [k for k in truth_by_occ.get((occ.slot_key, occ.business_date), []) if k not in BENIGN]
            codes = {
                f.code
                for f in occ.result.findings
                if f.severity.rank >= Severity.WARNING.rank or (f.code == "UNEXPECTED_DELIVERY")
            }
            warn_codes = {f.code for f in occ.result.findings if f.severity.rank >= Severity.WARNING.rank}
            for k in kinds:
                recall[k][1] += 1
                if codes & EXPECTED_CODE[k]:
                    recall[k][0] += 1
            if (
                "PARTIAL_HEALED" in truth_by_occ.get((occ.slot_key, occ.business_date), [])
                and "VOLUME_LOW" in warn_codes
            ):
                healed_alerting += 1
            if warn_codes:
                alerts += 1
                if kinds:
                    true_alerts += 1
                else:
                    false_codes.update(warn_codes)

    return QualityReport(
        occurrences=occ_n,
        alerts=alerts,
        true_alerts=true_alerts,
        recall={k: (v[0], v[1]) for k, v in recall.items()},
        healed_partials_still_alerting=healed_alerting,
        false_alerts_by_code=dict(false_codes.most_common()),
    )


def main() -> None:
    import json

    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=480)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--no-labels", action="store_true", help="simulate no analyst feedback")
    args = p.parse_args()
    rep = evaluate_quality(days=args.days, seed=args.seed, use_labels=not args.no_labels)
    print(json.dumps(rep.to_dict(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
