"""Detector quality gate on a fixed-seed labelled simulation.

If a change to detectors/baselines lowers recall or precision below these floors, CI fails. Raise the
floors when the model genuinely improves; never lower them without a written reason in the PR.
"""

from __future__ import annotations

from loadguard.sim.evaluate import evaluate_quality

RECALL_FLOOR = 0.93
PRECISION_FLOOR = 0.80
FALSE_ALERTS_PER_100_CEILING = 1.0


def test_detector_quality_gate():
    rep = evaluate_quality(days=480, seed=7)
    assert rep.overall_recall() >= RECALL_FLOOR, rep.to_dict()
    assert rep.precision >= PRECISION_FLOOR, rep.to_dict()
    assert rep.false_alerts_per_100 <= FALSE_ALERTS_PER_100_CEILING, rep.to_dict()
    for kind in ("MISSING", "LATE", "DUPLICATE_FILE", "UNIT_SCALE", "STALE", "NEGATIVE", "SYSTEMIC_OUTAGE"):
        caught, total = rep.recall[kind]
        assert caught == total, (kind, rep.to_dict())
    assert rep.healed_partials_still_alerting == 0
