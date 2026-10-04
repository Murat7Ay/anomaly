"""Turn analyst verdicts into concrete, reviewable contract changes (closing the feedback loop).

Suggestions never change anything by themselves: each yields a candidate spec that a human saves as
a draft, backtests, and a second human approves.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import time
from typing import Any

from loadguard.domain.contract import ContractSpec, Direction, Sensitivity
from loadguard.domain.fmt import METRIC_LABELS, pct

MIN_FALSE_ALARMS = 3
FALSE_ALARM_SHARE = 0.6
LOWER = {Sensitivity.HIGH: Sensitivity.MEDIUM, Sensitivity.MEDIUM: Sensitivity.LOW}
NOISY = ("FALSE_POSITIVE", "NEW_NORMAL")


@dataclass(frozen=True)
class ResolvedFinding:
    code: str
    metric: str | None
    slot_key: str
    resolution: str
    observed: float | None
    evidence: dict[str, Any]


@dataclass(frozen=True)
class Suggestion:
    key: str
    title: str
    rationale: str
    false_alarms: int
    confirmed: int
    proposed: ContractSpec

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "rationale": self.rationale,
            "false_alarms": self.false_alarms,
            "confirmed": self.confirmed,
            "proposed_spec": self.proposed.canonical(),
        }


def _share(fp: int, tp: int) -> float:
    return fp / (fp + tp) if fp + tp else 0.0


def suggest_tuning(spec: ContractSpec, resolved: list[ResolvedFinding]) -> list[Suggestion]:
    groups: dict[tuple[str, str | None], list[ResolvedFinding]] = defaultdict(list)
    for r in resolved:
        family = "VOLUME" if r.code in ("VOLUME_LOW", "VOLUME_HIGH") else r.code
        groups[(family, r.metric if family == "VOLUME" else r.slot_key)].append(r)

    out: list[Suggestion] = []
    for (family, sub), items in groups.items():
        fp = sum(1 for i in items if i.resolution in NOISY)
        tp = sum(1 for i in items if i.resolution == "TRUE_POSITIVE")
        if fp < MIN_FALSE_ALARMS or _share(fp, tp) < FALSE_ALARM_SHARE:
            continue
        stats = f"Son dönemde {fp + tp} etiketli uyarının {fp}'i yanlış alarm ({pct(_share(fp, tp))})."

        if family == "VOLUME" and sub:
            watch = next((w for w in spec.metrics if w.metric.value == sub), None)
            if watch is None:
                continue
            noisy_codes = [i.code for i in items if i.resolution in NOISY]
            if watch.sensitivity in LOWER:
                new = watch.model_copy(update={"sensitivity": LOWER[watch.sensitivity]})
                change = f"hassasiyet {watch.sensitivity.value} → {new.sensitivity.value}"
            elif all(c == "VOLUME_HIGH" for c in noisy_codes):
                new = watch.model_copy(update={"direction": Direction.LOW_ONLY})
                change = "yalnızca düşüş yönünü izle"
            elif all(c == "VOLUME_LOW" for c in noisy_codes):
                new = watch.model_copy(update={"direction": Direction.HIGH_ONLY})
                change = "yalnızca artış yönünü izle"
            else:
                continue
            metrics = [new if w.metric == watch.metric else w for w in spec.metrics]
            out.append(
                Suggestion(
                    key=f"volume:{sub}",
                    title=f"{METRIC_LABELS.get(sub, sub)}: {change}",
                    rationale=stats + " Eşik, kurumun doğal oynaklığına göre fazla dar görünüyor.",
                    false_alarms=fp,
                    confirmed=tp,
                    proposed=spec.model_copy(update={"metrics": metrics}),
                )
            )
        elif family in ("LATE_DELIVERY", "DELIVERY_AT_RISK") and sub:
            slot = spec.slot(sub)
            if slot is None:
                continue
            arrived = sorted(
                int(i.evidence["arrived"][:2]) * 60 + int(i.evidence["arrived"][3:5])
                for i in items
                if i.resolution in NOISY and isinstance(i.evidence.get("arrived"), str)
            )
            cur = slot.deadline.hour * 60 + slot.deadline.minute
            target = arrived[math.ceil(0.9 * len(arrived)) - 1] if arrived else cur + 60
            new_min = min(int(math.ceil((target + 15) / 30) * 30), 23 * 60 + 30)
            if new_min <= cur:
                new_min = min(cur + 30, 23 * 60 + 30)
            new_slot = slot.model_copy(update={"deadline": time(new_min // 60, new_min % 60)})
            out.append(
                Suggestion(
                    key=f"deadline:{sub}",
                    title=f"'{slot.label}' son teslim saati {slot.deadline:%H:%M} → {new_slot.deadline:%H:%M}",
                    rationale=stats
                    + " Kurumun fiili teslim saati sözleşmedeki saatten sistematik olarak geç.",
                    false_alarms=fp,
                    confirmed=tp,
                    proposed=spec.model_copy(
                        update={"slots": [new_slot if s.key == sub else s for s in spec.slots]}
                    ),
                )
            )
        elif family == "UNEXPECTED_DELIVERY" and spec.quality.unexpected_delivery != "IGNORE":
            out.append(
                Suggestion(
                    key="unexpected:ignore",
                    title="Takvim dışı teslimatlar için uyarı üretme",
                    rationale=stats + " Kurum ek teslimatları olağan iş akışının parçası olarak gönderiyor.",
                    false_alarms=fp,
                    confirmed=tp,
                    proposed=spec.model_copy(
                        update={"quality": spec.quality.model_copy(update={"unexpected_delivery": "IGNORE"})}
                    ),
                )
            )
        elif family == "ZERO_AMOUNT_RECORDS":
            peak = max((i.observed or 0) for i in items if i.resolution in NOISY)
            new_ratio = round(min(1.0, peak * 1.25), 3)
            out.append(
                Suggestion(
                    key="quality:zero_ratio",
                    title=f"Sıfır tutarlı kayıt eşiği {pct(spec.quality.max_zero_amount_ratio, 1)} → {pct(new_ratio, 1)}",
                    rationale=stats,
                    false_alarms=fp,
                    confirmed=tp,
                    proposed=spec.model_copy(
                        update={
                            "quality": spec.quality.model_copy(update={"max_zero_amount_ratio": new_ratio})
                        }
                    ),
                )
            )
    return out
