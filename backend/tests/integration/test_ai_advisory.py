from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy import select

from loadguard.ai.briefing import brief_view, generate_brief
from loadguard.ai.contract_assist import propose
from loadguard.ai.provider import AiResult, AiUnavailable
from loadguard.db.models import AiInteraction, Incident, Institution
from loadguard.db.session import unit_of_work

from .conftest import SPEC, TARGET, ingest, make_institution

pytestmark = pytest.mark.integration


class FakeProvider:
    name = "fake"

    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def complete_json(self, *, system: str, user: str, schema: dict[str, Any]) -> AiResult:
        self.calls.append(user)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return AiResult(r, self.name, "fake-model")


def _incident() -> Incident:
    make_institution("A1")
    ingest("A1", TARGET, 7, 30, records=30_000)
    with unit_of_work() as s:
        return s.scalars(select(Incident)).one()


def test_brief_flags_invented_numbers_and_keeps_runbook():
    inc = _incident()
    fake = FakeProvider(
        {
            "summary": "Kayıt sayısı 30.000; eşik 77.777 idi.",
            "customer_impact": "-",
            "likely_causes": ["Kısmi dosya"],
            "recommended_checks": ["Kurumu arayın"],
            "confidence": "medium",
        }
    )
    with unit_of_work() as s:
        row = generate_brief(s, inc.id, provider=fake)
        assert row.status == "OK"
        assert row.grounding["status"] == "UNVERIFIED_NUMBERS" and 77777.0 in row.grounding["unverified"]
        view = brief_view(s, s.get(Incident, inc.id))
    assert view["runbook"]["likely_causes"]  # deterministic runbook is always there
    assert view["ai"]["grounding"]["status"] == "UNVERIFIED_NUMBERS"
    assert "FACTS" in fake.calls[0]


def test_brief_falls_back_when_ai_unavailable():
    inc = _incident()
    with unit_of_work() as s:
        row = generate_brief(s, inc.id, provider=FakeProvider(AiUnavailable("down")))
        assert row.status == "ERROR"
        view = brief_view(s, s.get(Incident, inc.id))
    assert view["ai"] is None and view["runbook"]["recommended_checks"]


def test_contract_assist_repairs_once_then_validates():
    make_institution("A1", history_days=5)
    good = SPEC.model_copy(update={"timezone": "Europe/Istanbul"}).canonical()
    good["slots"][0]["deadline"] = "11:00:00"
    fake = FakeProvider(
        {"spec_json": json.dumps({"slots": []}), "explanation": "x", "assumptions": []},
        {"spec_json": json.dumps(good), "explanation": "Son teslim 11:00", "assumptions": []},
    )
    with unit_of_work() as s:
        inst = s.scalars(select(Institution)).one()
        res = propose(
            s,
            actor="ayse",
            institution_id=inst.id,
            base=SPEC,
            instruction="son teslimi 11'e çek",
            provider=fake,
        )
    assert res["ok"] and res["spec"]["slots"][0]["deadline"] == "11:00:00"
    assert "DÜZELT" in fake.calls[1]
    with unit_of_work() as s:
        assert s.scalars(select(AiInteraction)).one().status == "OK"
