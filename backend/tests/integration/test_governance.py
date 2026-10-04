from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from loadguard.db.models import AuditLog, Evaluation, ShadowResult
from loadguard.db.session import engine, unit_of_work
from loadguard.services import governance
from loadguard.services.common import audit, verify_audit_chain

from .conftest import TARGET, ingest, make_institution

pytestmark = pytest.mark.integration


def test_live_decisions_are_snapshotted_and_reproducible():
    make_institution("A1", history_days=15)
    ingest("A1", TARGET, 7, 30, records=35_000)
    with unit_of_work() as s:
        ev = s.scalars(select(Evaluation).order_by(Evaluation.evaluated_at.desc())).first()
        assert ev is not None and ev.snapshot_sha
        out = governance.verify_evaluation(s, ev.id)
    assert out["verifiable"] and out["snapshot_integrity"] and out["reproduced"]
    with unit_of_work() as s:
        sample = governance.verify_sample(s, 50)
    assert sample["checked"] > 0 and sample["reproduced"] == sample["checked"]


def test_decision_records_are_append_only_in_the_database():
    make_institution("A1", history_days=5)
    with pytest.raises(DBAPIError, match="append-only"), engine().begin() as c:
        c.execute(text("update evaluations set trigger = 'X'"))
    with pytest.raises(DBAPIError, match="append-only"), engine().begin() as c:
        c.execute(text("delete from input_snapshots"))


def test_audit_chain_detects_tampering():
    with unit_of_work() as s:
        for i in range(5):
            audit(s, "ayse", "test.action", "thing", i, n=i, note="ş")
    with unit_of_work() as s:
        assert verify_audit_chain(s) == {
            "ok": True,
            "rows_checked": 5,
            "head": s.scalars(select(AuditLog.row_hash).order_by(AuditLog.id.desc())).first(),
        }
    # A superuser bypassing the trigger can still change a row, but cannot hide it.
    with engine().begin() as c:
        c.execute(text("set local session_replication_role = replica"))
        c.execute(text("update audit_log set actor = 'mallory' where id = 3"))
    with unit_of_work() as s:
        res = verify_audit_chain(s)
    assert res["ok"] is False and res["first_broken_id"] == 3


def test_shadow_results_are_recorded_without_paging():
    make_institution("A1", history_days=15)
    ingest("A1", TARGET, 7, 30)
    with unit_of_work() as s:
        rows = s.scalars(select(ShadowResult)).all()
        assert rows and {r.challenger for r in rows} == {"mix-shift-v2"}
        report = governance.shadow_report(s, days=3650)
    assert report[0]["evaluated"] >= 1


def test_system_status_and_metrics():
    from loadguard.api.app import create_app

    with unit_of_work() as s:
        st = governance.system_status(s)
        assert st["worker"]["alive"] is False and st["healthy"] is False  # no worker running in tests
        governance.beat(s, ticked=True)
    with unit_of_work() as s:
        assert governance.system_status(s)["worker"]["alive"] is True
    body = TestClient(create_app()).get("/api/v1/metrics").text
    assert "loadguard_worker_alive 1" in body and "loadguard_build_info" in body
