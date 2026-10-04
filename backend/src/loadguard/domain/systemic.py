"""Cross-institution view: many billers missing at once is usually *our* problem (SFTP, network, parser).

One systemic incident replaces a storm of individual pages and points operators at the shared cause.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

WINDOW = timedelta(minutes=90)
MIN_MISSING = 3
MIN_SHARE = 0.5


@dataclass(frozen=True)
class DueOccurrence:
    occurrence_id: str
    institution_name: str
    deadline_utc: datetime
    missing: bool


@dataclass(frozen=True)
class SystemicSignal:
    window_start: datetime
    window_end: datetime
    missing: list[DueOccurrence]
    due_total: int

    @property
    def share(self) -> float:
        return len(self.missing) / self.due_total if self.due_total else 0.0


def detect_systemic(due: list[DueOccurrence], now: datetime) -> SystemicSignal | None:
    recent = [d for d in due if now - WINDOW <= d.deadline_utc <= now]
    missing = [d for d in recent if d.missing]
    if len(missing) < MIN_MISSING or len(missing) / max(len(recent), 1) < MIN_SHARE:
        return None
    return SystemicSignal(now - WINDOW, now, missing, len(recent))
