"""Business impact and priority: what an operator should look at first.

Severity says how sure/serious the signal is; priority adds *who is affected*: institution tier
(criticality agreed with the business) and the number of customers whose bill payment is at risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from loadguard.domain.contract import Severity
from loadguard.domain.model import Finding

P1_CUSTOMER_THRESHOLD = 50_000


class Priority(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"

    @property
    def rank(self) -> int:
        return int(self.value[1])


@dataclass(frozen=True)
class Impact:
    customers: float | None
    amount: float | None
    basis: str

    def to_dict(self) -> dict[str, Any]:
        return {"customers": self.customers, "amount": self.amount, "basis": self.basis}


def estimate_impact(
    findings: list[Finding], metrics: dict[str, float], reference: dict[str, float]
) -> Impact:
    best = Impact(None, None, "none")
    for f in findings:
        imp: Impact | None = None
        if f.code in ("MISSING_DELIVERY", "DELIVERY_AT_RISK"):
            imp = Impact(reference.get("customer_count"), reference.get("total_amount"), "expected_delivery")
        elif f.code == "VOLUME_LOW" and f.expected:
            ratio = max(0.0, 1 - (f.observed or 0) / f.expected)
            imp = Impact(
                (reference.get("customer_count") or 0) * ratio or None,
                (reference.get("total_amount") or 0) * ratio or None,
                "missing_share",
            )
        elif f.code in (
            "UNIT_SCALE_SUSPECT",
            "DUPLICATE_FILE",
            "NEGATIVE_AMOUNTS",
            "STALE_DATA",
            "LATE_DELIVERY",
        ):
            imp = Impact(metrics.get("customer_count"), metrics.get("total_amount"), "whole_delivery")
        if imp and (imp.customers or 0) > (best.customers or 0):
            best = imp
    return best


def priority_for(severity: Severity, tier: int, impact: Impact) -> Priority:
    customers = impact.customers or 0
    if severity == Severity.CRITICAL:
        return Priority.P1 if tier == 1 or customers >= P1_CUSTOMER_THRESHOLD else Priority.P2
    if severity == Severity.WARNING:
        return Priority.P2 if tier == 1 and customers >= P1_CUSTOMER_THRESHOLD else Priority.P3
    return Priority.P4


def demote(p: Priority) -> Priority:
    return Priority(f"P{min(4, p.rank + 1)}")
