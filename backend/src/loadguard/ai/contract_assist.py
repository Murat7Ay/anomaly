"""Natural language -> contract *draft proposal*.

Flow: analyst describes a change in Turkish -> model proposes a full spec -> strict schema validation
(+ one repair attempt) -> the analyst sees a diff and backtest -> saves as DRAFT -> a different person
approves. The model can never write to the contract store.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from loadguard.ai.provider import AiUnavailable, LlmProvider, get_provider
from loadguard.core import clock
from loadguard.db.models import AiInteraction, Institution
from loadguard.domain.contract import ContractSpec

SYSTEM_PROMPT = (
    "Bir borç dosyası izleme sisteminde kurum teslim sözleşmelerini (JSON) düzenleyen bir yardımcısın. "
    "Kullanıcının Türkçe talimatına göre MEVCUT sözleşmeyi değiştir ve TAM sözleşmeyi döndür.\n"
    "- Yalnızca talimatın gerektirdiği alanları değiştir; diğer her şeyi aynen koru.\n"
    "- Şemaya kesinlikle uy: saatler 'HH:MM:SS', haftanın günleri ISO (1=Pazartesi), anahtarlar küçük harf.\n"
    "- Emin olmadığın varsayımları 'assumptions' listesine yaz.\n"
    "- Değişiklik bir onay sürecinden geçecek; sen yalnızca öneri üretiyorsun."
)

ASSIST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "spec_json": {"type": "string", "description": "Tam sözleşme, JSON metni olarak"},
        "explanation": {"type": "string"},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["spec_json", "explanation", "assumptions"],
    "additionalProperties": False,
}


def propose(
    s: Session,
    *,
    actor: str,
    institution_id: Any,
    base: ContractSpec,
    instruction: str,
    provider: LlmProvider | None = None,
) -> dict[str, Any]:
    provider = provider or get_provider()
    inst = s.get(Institution, institution_id)
    schema_hint = json.dumps(ContractSpec.model_json_schema(), ensure_ascii=False)
    user = (
        f"KURUM: {inst.name if inst else '-'}\nTALİMAT: {instruction}\n\nMEVCUT_SÖZLEŞME:\n"
        f"{json.dumps(base.canonical(), ensure_ascii=False, indent=1)}\n\nŞEMA:\n{schema_hint}"
    )
    started = time.monotonic()
    row = AiInteraction(
        at=clock.now(),
        actor=actor,
        purpose="CONTRACT_ASSIST",
        provider=provider.name,
        entity_type="institution",
        entity_id=str(institution_id),
        request={"instruction": instruction, "prompt_sha256": hashlib.sha256(user.encode()).hexdigest()},
        response=None,
        grounding=None,
        status="ERROR",
        model=None,
        latency_ms=None,
    )
    result: dict[str, Any]
    try:
        attempt_user = user
        errors: list[Any] = []
        for _ in range(2):
            res = provider.complete_json(system=SYSTEM_PROMPT, user=attempt_user, schema=ASSIST_SCHEMA)
            row.model = res.model
            try:
                spec = ContractSpec.model_validate_json(res.data["spec_json"])
                result = {
                    "ok": True,
                    "spec": spec.canonical(),
                    "explanation": res.data.get("explanation", ""),
                    "assumptions": res.data.get("assumptions", []),
                }
                row.status = "OK"
                break
            except (ValidationError, ValueError) as e:
                errors = e.errors() if isinstance(e, ValidationError) else [str(e)]
                attempt_user = (
                    user
                    + "\n\nÖNCEKİ YANITIN ŞEMAYA UYMADI, DÜZELT:\n"
                    + json.dumps(errors, default=str)[:4000]
                )
        else:
            result = {
                "ok": False,
                "error": "Model şemaya uygun bir sözleşme üretemedi.",
                "details": errors[:10],
            }
    except AiUnavailable as e:
        result = {"ok": False, "error": str(e)}
    row.response = result
    row.latency_ms = int((time.monotonic() - started) * 1000)
    s.add(row)
    return result
