from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from loadguard.core.errors import Forbidden, Invalid
from loadguard.db.models import Incident, IncidentEvent, Institution, Job, Load, Occurrence
from loadguard.db.session import unit_of_work
from loadguard.services import contracts, incidents
from loadguard.services.pipeline import LoadIn
from loadguard.services.pipeline import ingest as ingest_svc

from .conftest import SPEC, TARGET, at, ingest, make_institution, set_now, sweep_at

pytestmark = pytest.mark.integration


def _incidents(code: str | None = None) -> list[Incident]:
    with unit_of_work() as s:
        q = select(Incident).order_by(Incident.opened_at)
        if code:
            inst = s.scalars(select(Institution).where(Institution.code == code)).one()
            q = q.where(Incident.institution_id == inst.id)
        return list(s.scalars(q))


def _occ(code: str) -> Occurrence:
    with unit_of_work() as s:
        inst = s.scalars(select(Institution).where(Institution.code == code)).one()
        return s.scalars(
            select(Occurrence).where(Occurrence.institution_id == inst.id, Occurrence.business_date == TARGET)
        ).one()


def test_history_is_quiet_and_learns():
    make_institution("A1")
    assert _incidents() == []
    ingest("A1", TARGET, 7, 40)
    occ = _occ("A1")
    assert occ.status == "RECEIVED"
    assert occ.baselines["record_count"]["expected"] == pytest.approx(102_000, rel=0.03)


def test_missing_then_late_updates_same_incident():
    make_institution("A1")
    with unit_of_work() as s:
        from loadguard.services.pipeline import materialize

        set_now(at(TARGET, 0, 5))
        materialize(s, TARGET)
    sweep_at(at(TARGET, 8, 30))
    assert _occ("A1").status == "AT_RISK"
    sweep_at(at(TARGET, 10, 1))
    [inc] = _incidents()
    assert (inc.status, inc.priority, inc.codes) == ("OPEN", "P1", ["MISSING_DELIVERY"])
    with unit_of_work() as s:
        kinds = {j.kind for j in s.scalars(select(Job))}
    assert {"AI_BRIEF", "NOTIFY"} <= kinds

    ingest("A1", TARGET, 11, 15)
    [inc] = _incidents()
    assert inc.codes == ["LATE_DELIVERY"] and inc.severity == "WARNING" and inc.status == "OPEN"
    with unit_of_work() as s:
        events = [e.kind for e in s.scalars(select(IncidentEvent).where(IncidentEvent.incident_id == inc.id))]
    assert "UPDATED" in events


def test_partial_file_then_complement_auto_resolves():
    make_institution("A1")
    ingest("A1", TARGET, 7, 30, records=35_000)
    [inc] = _incidents()
    assert inc.category == "VOLUME" and "VOLUME_LOW" in inc.codes
    ingest("A1", TARGET, 8, 45, records=67_000)
    [inc] = _incidents()
    assert inc.status == "RESOLVED" and inc.resolution == "AUTO_CLEARED"


def test_duplicate_file_and_idempotent_ingest():
    make_institution("A1")
    ingest("A1", TARGET, 7, 30, content_hash="same-content-xyz", ext="first")
    with unit_of_work() as s:
        _, created = ingest_svc(
            s,
            LoadIn(
                institution_code="A1",
                external_id="first",
                received_at=at(TARGET, 7, 30),
                content_hash="x" * 10,
                record_count=1,
                total_amount=1,
                customer_count=1,
            ),
        )
    assert created is False
    nxt = TARGET.replace(day=17)
    ingest("A1", nxt, 7, 30, content_hash="same-content-xyz", ext="second")
    assert any("DUPLICATE_FILE" in i.codes for i in _incidents())


def test_resolution_feeds_learning_and_requires_note():
    make_institution("A1")
    ingest("A1", TARGET, 7, 30, records=30_000)
    [inc] = _incidents()
    with unit_of_work() as s, pytest.raises(Invalid):
        incidents.resolve(s, actor="ayse", incident_id=inc.id, resolution="FALSE_POSITIVE", note=None)
    with unit_of_work() as s:
        incidents.acknowledge(s, actor="ayse", incident_id=inc.id)
        incidents.resolve(s, actor="ayse", incident_id=inc.id, resolution="TRUE_POSITIVE", note="kısmi dosya")
    assert _occ("A1").excluded_from_baseline is True


def test_four_eyes_contract_approval():
    make_institution("A1")
    with unit_of_work() as s:
        inst = s.scalars(select(Institution)).one()
        relaxed = SPEC.model_copy(update={"timezone": "Europe/Istanbul", "metrics": SPEC.metrics[:1]})
        set_now(at(TARGET, 12))
        cv = contracts.create_draft(
            s, actor="ayse", institution_id=inst.id, spec=relaxed, effective_from=TARGET, change_note="test"
        )
        contracts.submit(s, actor="ayse", version_id=cv.id)
        assert cv.backtest is not None and cv.backtest["current"] is not None
        cv_id = cv.id
    with unit_of_work() as s, pytest.raises(Forbidden):
        contracts.decide(s, actor="ayse", role="APPROVER", version_id=cv_id, approve=True, note=None)
    with unit_of_work() as s, pytest.raises(Forbidden):
        contracts.decide(s, actor="can", role="ANALYST", version_id=cv_id, approve=True, note=None)
    with unit_of_work() as s:
        cv = contracts.decide(s, actor="mehmet", role="APPROVER", version_id=cv_id, approve=True, note="ok")
        assert cv.status == "APPROVED"
        eff = contracts.effective_contract(s, cv.institution_id, TARGET)
        assert eff is not None and eff[0].version == 2


def test_systemic_outage_groups_incidents():
    for code in ("S1", "S2", "S3", "S4"):
        make_institution(code, tier=2, history_days=12)
    with unit_of_work() as s:
        from loadguard.services.pipeline import materialize

        set_now(at(TARGET, 0, 5))
        materialize(s, TARGET)
    ingest("S4", TARGET, 7, 40)
    sweep_at(at(TARGET, 10, 5))
    incs = _incidents()
    parents = [i for i in incs if i.kind == "SYSTEMIC"]
    assert len(parents) == 1
    children = [i for i in incs if i.parent_id == parents[0].id]
    assert len(children) == 3 and all(c.priority == "P2" for c in children)  # P1 (95k customers) demoted once


def test_api_auth_and_overview():
    from loadguard.api.app import create_app

    make_institution("A1", history_days=10)
    client = TestClient(create_app())
    r = client.get("/api/v1/overview")
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    tok = client.post("/api/v1/auth/dev-login", json={"username": "ayse"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/v1/overview", headers=h).status_code == 200
    insts = client.get("/api/v1/institutions", headers=h).json()
    assert insts[0]["code"] == "A1"
    r = client.post("/api/v1/ingest/loads", json={}, headers={"X-Api-Key": "wrong"})
    assert r.status_code == 401
    with unit_of_work() as s:
        assert s.scalars(select(Load)).first() is not None
