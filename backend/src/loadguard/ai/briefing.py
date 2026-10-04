"""Incident brief for the analyst: a deterministic runbook always, an AI narrative when available.

The AI sees only the facts the engine already produced and is instructed (and checked) not to
change, soften or second-guess the decision. Its output is labelled as advisory everywhere.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from loadguard.ai.grounding import check_grounding
from loadguard.ai.provider import AiUnavailable, LlmProvider, get_provider
from loadguard.core import clock
from loadguard.db.models import AiInteraction, Incident, Institution, Occurrence
from loadguard.domain import fmt

RUNBOOK: dict[str, dict[str, list[str]]] = {
    "MISSING_DELIVERY": {
        "causes": [
            "Kurum tarafında üretim/aktarım işi çalışmadı",
            "SFTP/API bağlantı veya kimlik doğrulama sorunu",
            "Dosya geldi ama bizim alım/parçalama adımında takıldı",
        ],
        "checks": [
            "Alım altyapısında (SFTP klasörü, API gateway logları) dosya izi var mı bakın",
            "Kurumun teknik irtibatını arayıp gönderim durumunu sorun",
            "Aynı saatte başka kurumlarda da gecikme var mı kontrol edin (ortak neden)",
        ],
    },
    "DELIVERY_AT_RISK": {
        "causes": ["Kurum tarafında gecikme", "Ağ/aktarım yavaşlığı"],
        "checks": [
            "Kurumu son teslim saatinden önce proaktif olarak arayın",
            "Alım altyapısında kuyrukta bekleyen dosya olup olmadığına bakın",
        ],
    },
    "LATE_DELIVERY": {
        "causes": ["Kurum tarafında geç üretim", "Aktarımda yeniden deneme"],
        "checks": [
            "Gecikme süresince ödeme kanallarında hata/şikâyet oluştu mu kontrol edin",
            "Tekrarlıyorsa sözleşmedeki son teslim saatini kurumla yeniden görüşün",
        ],
    },
    "VOLUME_LOW": {
        "causes": ["Kısmi dosya (eksik parça)", "Kurumda filtre/segment hatası", "Bilinen dönemsel düşüş"],
        "checks": [
            "Aynı gün tamamlayıcı dosya bekleniyor mu kurumla teyit edin",
            "Dosyadaki bölge/abone grubu dağılımını önceki günle karşılaştırın",
        ],
    },
    "VOLUME_HIGH": {
        "causes": [
            "Mükerrer/birleştirilmiş içerik",
            "Toplu yeniden faturalama veya kampanya",
            "Tarife değişikliği",
        ],
        "checks": [
            "Kurumdan olağandışı bir faturalama çalışması olup olmadığını sorun",
            "Kalıcı bir değişimse olayı 'Yeni normal' olarak kapatın",
        ],
    },
    "UNIT_SCALE_SUSPECT": {
        "causes": ["Tutar alanında kuruş/TL birim karışıklığı", "Dosya formatı/sürüm değişikliği"],
        "checks": [
            "ACİL: Örnek birkaç kaydın tutarını kurum ekranıyla karşılaştırın",
            "Doğrulanana kadar bu dosyayla tahsilatı durdurmayı değerlendirin",
        ],
    },
    "DUPLICATE_FILE": {
        "causes": ["Kurum aynı dosyayı yeniden gönderdi", "Bizim tarafta yeniden işleme"],
        "checks": [
            "Borçların çift yüklenip yüklenmediğini kontrol edin",
            "Gerekirse ikinci yüklemeyi geri alın",
        ],
    },
    "STALE_DATA": {
        "causes": ["Kurum dünkü dosyayı yeniden üretti", "Kurumun kaynak sistemi güncellenmedi"],
        "checks": ["Bugün ödenen borçların dosyada hâlâ görünüp görünmediğini kontrol edin"],
    },
    "ZERO_AMOUNT_RECORDS": {
        "causes": ["Tutar alanı boş/eşleme hatası", "Mahsuplaşmış kayıtlar"],
        "checks": ["Sıfır tutarlı kayıtlardan örnek alıp kurumla teyit edin"],
    },
    "NEGATIVE_AMOUNTS": {
        "causes": ["İade/alacak kayıtları borç dosyasına karışmış", "İşaret hatası"],
        "checks": ["Negatif kayıtların ödeme kanallarında nasıl göründüğünü kontrol edin"],
    },
    "DUPLICATE_RECORDS": {
        "causes": ["Kaynak sistemde birleştirme hatası"],
        "checks": ["Mükerrer kayıt örneklerini kurumla paylaşın"],
    },
    "LIMIT_BREACH": {
        "causes": ["İş kuralının sınırı aşıldı"],
        "checks": ["Kuralın notunda belirtilen prosedürü uygulayın"],
    },
    "SYSTEMIC_OUTAGE": {
        "causes": [
            "Bizim alım altyapımızda (SFTP sunucusu, ağ, entegrasyon servisi) kesinti",
            "Ortak bir aracı (ör. ağ sağlayıcı) sorunu",
        ],
        "checks": [
            "Önce kendi alım servislerinin sağlığını kontrol edin",
            "Altyapı ekibine eskalasyon yapın",
            "Kurumları tek tek aramayın; ortak duyuru yapın",
        ],
    },
}

SYSTEM_PROMPT = (
    "Bir fatura tahsilat operasyonunda çalışan analistlere yardımcı bir asistansın. "
    "Görevin, sistemin ZATEN VERDİĞİ bir uyarıyı Türkçe ve kısa biçimde açıklamak.\n"
    "Kurallar:\n"
    "- Karar yetkin yok. Uyarının doğru ya da yanlış olduğunu söyleme; şiddetini veya önceliğini değiştirme.\n"
    "- Yalnızca FACTS içindeki bilgileri kullan. FACTS'te olmayan hiçbir sayı, tarih, kurum adı veya olay uydurma.\n"
    "- Sayıları FACTS'teki değerlerden al; Türkçe biçimde ve okunur yuvarlamayla yaz "
    "(ör. 144.355 TL, %0,16, 1 sa 14 dk). Ham ondalık dizileri kopyalama.\n"
    "- Olası nedenleri olasılık diliyle ifade et; kesin hüküm verme.\n"
    "- Önerilen kontroller somut ve operasyonel olsun; operasyon analistinin hemen yapabileceği adımlar."
)

BRIEF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "2-3 cümle, ne oldu ve neden önemli"},
        "customer_impact": {"type": "string"},
        "likely_causes": {"type": "array", "items": {"type": "string"}},
        "recommended_checks": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["summary", "customer_impact", "likely_causes", "recommended_checks", "confidence"],
    "additionalProperties": False,
}


def _tidy(v: Any) -> Any:
    """Round floats so the model sees (and repeats) human-scale numbers, not 0.0016508805567020004."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, float):
        if v == int(v) and abs(v) >= 1:
            return int(v)
        return round(v, 2) if abs(v) >= 1 else round(v, 4)
    if isinstance(v, dict):
        return {k: _tidy(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_tidy(x) for x in v]
    return v


def build_facts(s: Session, inc: Incident) -> dict[str, Any]:
    inst = s.get(Institution, inc.institution_id) if inc.institution_id else None
    occ = s.get(Occurrence, inc.occurrence_id) if inc.occurrence_id else None
    facts: dict[str, Any] = {
        "incident": {
            "number": inc.number,
            "title": inc.title,
            "severity": inc.severity,
            "priority": inc.priority,
            "category": inc.category,
            "codes": inc.codes,
            "impact_customers": inc.impact_customers,
            "impact_amount": inc.impact_amount,
        },
    }
    if inst:
        facts["institution"] = {"name": inst.name, "sector": inst.sector, "tier": inst.tier}
    if occ:
        facts["delivery"] = {
            "slot": occ.slot_key,
            "business_date": occ.business_date.isoformat(),
            "status": occ.status,
            "file_count": occ.load_count,
            "metrics": occ.metrics,
        }
        facts["findings"] = [
            {
                k: f.get(k)
                for k in ("code", "severity", "message", "metric", "observed", "expected", "lower", "upper")
            }
            for f in occ.findings
        ]
        recent = s.scalars(
            select(Occurrence)
            .where(
                Occurrence.institution_id == occ.institution_id,
                Occurrence.slot_key == occ.slot_key,
                Occurrence.business_date < occ.business_date,
                Occurrence.business_date >= occ.business_date - timedelta(days=30),
            )
            .order_by(Occurrence.business_date.desc())
            .limit(10)
        ).all()
        facts["recent_deliveries"] = [
            {"date": o.business_date.isoformat(), "status": o.status, "max_severity": o.max_severity}
            for o in recent
        ]
    return _tidy(facts)  # type: ignore[no-any-return]


def deterministic_brief(inc: Incident, facts: dict[str, Any]) -> dict[str, Any]:
    causes: list[str] = []
    checks: list[str] = []
    for code in inc.codes:
        rb = RUNBOOK.get(code, {})
        causes += [c for c in rb.get("causes", []) if c not in causes]
        checks += [c for c in rb.get("checks", []) if c not in checks]
    impact = "Doğrudan müşteri etkisi hesaplanmadı."
    if inc.impact_customers:
        impact = f"Yaklaşık {fmt.num(inc.impact_customers)} müşterinin borç ödemesi etkilenebilir"
        impact += f" (≈{fmt.money(inc.impact_amount)})." if inc.impact_amount else "."
    msgs = [f["message"] for f in facts.get("findings", []) if f.get("severity") != "INFO"]
    return {
        "summary": " ".join(msgs[:2]) or inc.title,
        "customer_impact": impact,
        "likely_causes": causes,
        "recommended_checks": checks,
    }


def generate_brief(
    s: Session, incident_id: uuid.UUID, *, actor: str = "system", provider: LlmProvider | None = None
) -> AiInteraction:
    inc = s.get(Incident, incident_id)
    if inc is None:
        raise ValueError("incident not found")
    facts = build_facts(s, inc)
    provider = provider or get_provider()
    user = "FACTS:\n" + json.dumps(facts, ensure_ascii=False, indent=1, default=str)
    req = {"system": SYSTEM_PROMPT, "user": user}
    started = time.monotonic()
    row = AiInteraction(
        at=clock.now(),
        actor=actor,
        purpose="INCIDENT_BRIEF",
        provider=provider.name,
        entity_type="incident",
        entity_id=str(inc.id),
        request={"prompt_sha256": hashlib.sha256(user.encode()).hexdigest(), "facts": facts},
        response=None,
        grounding=None,
        status="FALLBACK",
        model=None,
        latency_ms=None,
    )
    try:
        res = provider.complete_json(system=req["system"], user=req["user"], schema=BRIEF_SCHEMA)
        texts = [
            res.data.get("summary", ""),
            res.data.get("customer_impact", ""),
            *res.data.get("likely_causes", []),
            *res.data.get("recommended_checks", []),
        ]
        row.response, row.model, row.status = res.data, res.model, "OK"
        row.grounding = check_grounding(texts, facts)
    except AiUnavailable as e:
        row.response = {"error": str(e)}
        row.status = "FALLBACK" if provider.name == "none" else "ERROR"
    row.latency_ms = int((time.monotonic() - started) * 1000)
    s.add(row)
    s.flush()
    return row


def brief_view(s: Session, inc: Incident) -> dict[str, Any]:
    facts = build_facts(s, inc)
    latest = s.scalars(
        select(AiInteraction)
        .where(
            AiInteraction.entity_type == "incident",
            AiInteraction.entity_id == str(inc.id),
            AiInteraction.purpose == "INCIDENT_BRIEF",
        )
        .order_by(AiInteraction.at.desc())
        .limit(1)
    ).first()
    ai = None
    if latest is not None and latest.status == "OK":
        ai = {
            **(latest.response or {}),
            "model": latest.model,
            "provider": latest.provider,
            "generated_at": latest.at.isoformat(),
            "grounding": latest.grounding,
        }
    return {
        "runbook": deterministic_brief(inc, facts),
        "ai": ai,
        "ai_status": latest.status if latest else "NOT_REQUESTED",
        "ai_error": (latest.response or {}).get("error") if latest and latest.status != "OK" else None,
        "disclaimer": "Yapay zekâ metni yalnızca bilgilendirme amaçlıdır; karar, kural ve eşikler deterministik "
        "motordan gelir ve yapay zekâ bunları değiştiremez.",
    }
