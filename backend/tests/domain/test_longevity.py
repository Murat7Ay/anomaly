"""Properties that must hold for a decade: reproducible decisions, readable old specs, safe model evolution."""

from __future__ import annotations

import json

import pytest

from loadguard.domain.challengers import CHALLENGERS, detect_mix_shift
from loadguard.domain.contract_migrations import CURRENT_SCHEMA_VERSION, SpecMigrationError, load_spec, upcast
from loadguard.domain.engine import evaluate
from loadguard.domain.model import HistoryPoint
from loadguard.domain.snapshot import decision_summary, fingerprint, from_payload, to_payload, verify

from .conftest import at, load
from .test_engine import TARGET, _ctx, _history


@pytest.mark.parametrize(
    "case",
    ["normal", "missing", "partial", "duplicate"],
)
def test_snapshot_round_trip_reproduces_decision(cal, daily_spec, case):
    lf = load(TARGET, 7, 40, records=40_000 if case == "partial" else 100_000)
    loads = [] if case == "missing" else [lf]
    seen = frozenset({lf.content_hash}) if case == "duplicate" else frozenset()
    ctx = _ctx(cal, daily_spec, loads, at(TARGET, 11), seen=seen)
    payload = to_payload(ctx)
    # survives a JSON round trip (that is how it is stored)
    restored = from_payload(json.loads(json.dumps(payload)))
    assert decision_summary(evaluate(restored)) == decision_summary(evaluate(ctx))
    assert fingerprint(payload) == fingerprint(json.loads(json.dumps(payload)))


def test_verify_detects_behaviour_change(cal, daily_spec):
    ctx = _ctx(cal, daily_spec, [load(TARGET, 7, 40, records=40_000)], at(TARGET, 11))
    r = evaluate(ctx)
    stored = {"status": r.status.value, "findings": [f.to_dict() for f in r.findings]}
    assert verify(to_payload(ctx), stored)["reproduced"] is True
    tampered = {**stored, "findings": []}
    assert verify(to_payload(ctx), tampered)["reproduced"] is False


def test_fingerprint_changes_when_inputs_change(cal, daily_spec):
    a = to_payload(_ctx(cal, daily_spec, [load(TARGET, 7, 40)], at(TARGET, 11)))
    b = to_payload(_ctx(cal, daily_spec, [load(TARGET, 7, 41)], at(TARGET, 11)))
    assert fingerprint(a) != fingerprint(b)


def test_old_spec_versions_are_upcast(daily_spec):
    legacy = daily_spec.canonical()
    legacy["deliveries"] = legacy.pop("slots")
    legacy["schema_version"] = 0
    spec = load_spec(legacy)
    assert spec.slots == daily_spec.slots and spec.schema_version == CURRENT_SCHEMA_VERSION


def test_future_spec_versions_fail_loudly(daily_spec):
    with pytest.raises(SpecMigrationError):
        upcast({**daily_spec.canonical(), "schema_version": CURRENT_SCHEMA_VERSION + 1})


def test_challenger_finds_segment_drop_champion_misses(cal, daily_spec):
    hist = tuple(
        HistoryPoint(
            **{**p.__dict__, "metrics": {**p.metrics, "customer_count": p.metrics["record_count"] * 0.95}}
        )
        for p in _history(cal)
    )
    # records normal, customers -25%: a segment of subscribers silently missing
    lf = load(TARGET, 7, 40, customer_count=71_000)
    ctx = _ctx(cal, daily_spec, [lf], at(TARGET, 11), history=hist)
    assert not any(f.code == "MIX_SHIFT" for f in evaluate(ctx).findings)
    assert [f.metric for f in detect_mix_shift(ctx, ratios=("records_per_customer",))] == [
        "records_per_customer"
    ]
    r = CHALLENGERS["mix-shift-v2"](ctx)
    assert "MIX_SHIFT" in {f.code for f in r.findings} and r.engine_version.endswith("mix-shift-v2")
