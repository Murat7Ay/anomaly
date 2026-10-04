"""Decision snapshots: everything an evaluation saw, serialised so it can be re-run years later.

Why: history changes after the fact (analyst labels exclude points, new normals reset levels, holidays
get corrected). A decision is only auditable if the *exact* inputs are kept. Snapshots are
content-addressed (sha256 of canonical JSON) so identical inputs are stored once.

`verify()` re-runs the current engine on a stored snapshot and reports whether the decision is
reproduced. Run it on samples before every engine upgrade: it quantifies behaviour change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any

from loadguard.domain.calendar import BusinessCalendar, MonthPhase
from loadguard.domain.contract import ContractSpec
from loadguard.domain.contract_migrations import load_spec
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.engine import EvalResult, evaluate
from loadguard.domain.model import HistoryPoint, LoadFacts
from loadguard.domain.schedule import ExpectedOccurrence

SNAPSHOT_FORMAT = 1
CALENDAR_PAD_DAYS = 45


def _canon(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def to_payload(ctx: EvalContext) -> dict[str, Any]:
    d = ctx.business_date
    lo, hi = d - timedelta(days=CALENDAR_PAD_DAYS), d + timedelta(days=CALENDAR_PAD_DAYS)
    # history month phases are already materialised on the points; only the window near d is needed
    return {
        "format": SNAPSHOT_FORMAT,
        "spec": ctx.spec.canonical(),
        "calendar": {
            "code": ctx.calendar.code,
            "window": [lo.isoformat(), hi.isoformat()],
            "holidays": sorted(h.isoformat() for h in ctx.calendar.holidays if lo <= h <= hi),
            "half_days": sorted(h.isoformat() for h in ctx.calendar.half_days if lo <= h <= hi),
            "weekend": sorted(ctx.calendar.weekend),
        },
        "slot_key": ctx.slot_key,
        "business_date": d.isoformat(),
        "expected": None
        if ctx.expected is None
        else {
            "slot_key": ctx.expected.slot_key,
            "business_date": ctx.expected.business_date.isoformat(),
            "nominal_date": ctx.expected.nominal_date.isoformat(),
            "window_start_utc": ctx.expected.window_start_utc.isoformat(),
            "deadline_utc": ctx.expected.deadline_utc.isoformat(),
        },
        "loads": [{**asdict(lf), "received_at": lf.received_at.isoformat()} for lf in ctx.loads],
        "history": [
            {
                "d": p.business_date.isoformat(),
                "wd": p.weekday,
                "ph": p.month_phase.value,
                "m": p.metrics,
                "a": p.first_arrival_minutes,
                "x": p.excluded,
                "r": p.regime_break,
            }
            for p in ctx.history
        ],
        "seen_hashes": sorted(ctx.seen_hashes),
        "now": ctx.now.isoformat(),
    }


def fingerprint(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canon(payload).encode()).hexdigest()


def from_payload(p: dict[str, Any]) -> EvalContext:
    spec: ContractSpec = load_spec(p["spec"])
    c = p["calendar"]
    cal = BusinessCalendar(
        code=c["code"],
        holidays=frozenset(date.fromisoformat(x) for x in c["holidays"]),
        half_days=frozenset(date.fromisoformat(x) for x in c["half_days"]),
        weekend=frozenset(c["weekend"]),
    )
    e = p["expected"]
    expected = (
        None
        if e is None
        else ExpectedOccurrence(
            slot_key=e["slot_key"],
            business_date=date.fromisoformat(e["business_date"]),
            nominal_date=date.fromisoformat(e["nominal_date"]),
            window_start_utc=datetime.fromisoformat(e["window_start_utc"]),
            deadline_utc=datetime.fromisoformat(e["deadline_utc"]),
        )
    )
    return EvalContext(
        spec=spec,
        calendar=cal,
        slot_key=p["slot_key"],
        business_date=date.fromisoformat(p["business_date"]),
        expected=expected,
        loads=tuple(
            LoadFacts(**{**lf, "received_at": datetime.fromisoformat(lf["received_at"])}) for lf in p["loads"]
        ),
        history=tuple(
            HistoryPoint(
                business_date=date.fromisoformat(h["d"]),
                weekday=h["wd"],
                month_phase=MonthPhase(h["ph"]),
                metrics=h["m"],
                first_arrival_minutes=h["a"],
                excluded=h["x"],
                regime_break=h["r"],
            )
            for h in p["history"]
        ),
        seen_hashes=frozenset(p["seen_hashes"]),
        now=datetime.fromisoformat(p["now"]),
    )


def decision_summary(r: EvalResult) -> dict[str, Any]:
    """The parts of a result that constitute the decision (what must be reproducible)."""
    return {
        "status": r.status.value,
        "findings": sorted((f.code, f.severity.value, f.metric or "") for f in r.findings),
    }


def verify(payload: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    """Re-run the engine on a snapshot and compare with the stored decision."""
    rerun = decision_summary(evaluate(from_payload(payload)))
    before = {
        "status": stored["status"],
        "findings": sorted((f["code"], f["severity"], f.get("metric") or "") for f in stored["findings"]),
    }
    rerun_json = json.loads(_canon(rerun))
    return {"reproduced": rerun_json == json.loads(_canon(before)), "stored": before, "rerun": rerun_json}
