from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from loadguard.domain.calendar import BusinessCalendar
from loadguard.domain.contract import ContractSpec, DeliverySlot
from loadguard.domain.model import HistoryPoint, LoadFacts
from loadguard.domain.schedule import ExpectedOccurrence


@dataclass(frozen=True)
class EvalContext:
    """Everything needed to judge one occurrence. Built identically by live runs, replays and backtests."""

    spec: ContractSpec
    calendar: BusinessCalendar
    slot_key: str
    business_date: date
    expected: ExpectedOccurrence | None  # None: unscheduled delivery
    loads: tuple[LoadFacts, ...]
    history: tuple[HistoryPoint, ...]  # same slot, strictly before business_date
    seen_hashes: frozenset[str]  # content hashes the institution delivered before these loads
    now: datetime
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def slot(self) -> DeliverySlot | None:
        return self.spec.slot(self.slot_key)
