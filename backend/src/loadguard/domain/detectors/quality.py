"""Content quality: the classic ways a debt file is wrong even when it arrives on time.

* duplicate file        -> customers could be billed twice
* stale data            -> biller re-sent yesterday's numbers; payments go against outdated debts
* unit scale (x100/x1000) -> kuruş/TL confusion; every customer sees a wrong amount
* zero / negative / duplicate records
"""

from __future__ import annotations

import statistics

from loadguard.domain import fmt
from loadguard.domain.contract import Severity
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.model import Category, Finding

UNIT_FACTORS = (100.0, 1000.0)
UNIT_TOLERANCE = 0.35  # ratio within ±35% of a factor counts as a unit-scale suspect


def unit_scale_factor(ratio: float) -> float | None:
    for f in UNIT_FACTORS:
        for target in (f, 1 / f):
            if abs(ratio / target - 1) <= UNIT_TOLERANCE:
                return target
    return None


def detect_quality(ctx: EvalContext) -> list[Finding]:
    m = ctx.metrics
    q = ctx.spec.quality
    out: list[Finding] = []
    if not ctx.loads:
        return out

    if q.detect_duplicate_file:
        seen = set(ctx.seen_hashes)
        for lf in ctx.loads:
            if lf.content_hash in seen:
                out.append(
                    Finding(
                        code="DUPLICATE_FILE",
                        category=Category.QUALITY,
                        severity=Severity.CRITICAL,
                        message=(
                            "Bu dosyanın içeriği daha önce alınmış bir dosyayla birebir aynı (içerik özeti eşleşiyor). "
                            "Borçların mükerrer yüklenmesi ve çift tahsilat riski var."
                        ),
                        evidence={"load_id": lf.id, "content_hash": lf.content_hash[:16]},
                    )
                )
                break
            seen.add(lf.content_hash)

    prev = next((p for p in reversed(ctx.history) if p.metrics), None)
    if (
        q.detect_stale_data
        and prev is not None
        and not any(f.code == "DUPLICATE_FILE" for f in out)
        and all(prev.metrics.get(k) == m.get(k) for k in ("record_count", "total_amount", "customer_count"))
    ):
        out.append(
            Finding(
                code="STALE_DATA",
                category=Category.QUALITY,
                severity=Severity.WARNING,
                message=(
                    f"Kayıt sayısı, toplam tutar ve müşteri sayısı {prev.business_date:%d.%m.%Y} teslimatıyla "
                    "birebir aynı. Kurum borç verisini güncellememiş olabilir."
                ),
                evidence={"previous_date": prev.business_date.isoformat()},
            )
        )

    if q.detect_unit_scale and m.get("record_count"):
        hist_avg = [
            p.metrics["avg_amount"]
            for p in ctx.history[-30:]
            if not p.excluded and p.metrics.get("avg_amount")
        ]
        if len(hist_avg) >= 4:
            ref = statistics.median(hist_avg)
            ratio = m["avg_amount"] / ref if ref else 0.0
            factor = unit_scale_factor(ratio) if ratio > 0 else None
            if factor is not None:
                label = f"x{int(factor)}" if factor > 1 else f"/{round(1 / factor)}"
                out.append(
                    Finding(
                        code="UNIT_SCALE_SUSPECT",
                        category=Category.QUALITY,
                        severity=Severity.CRITICAL,
                        message=(
                            f"Ortalama borç tutarı olağan değerin {label} katı ({fmt.money(m['avg_amount'])} vs "
                            f"{fmt.money(ref)}), kayıt sayısı ise normal. Kuruş/TL birim hatası şüphesi: "
                            "müşterilere yanlış tutar gösterilebilir."
                        ),
                        metric="avg_amount",
                        observed=m["avg_amount"],
                        expected=ref,
                        score=ratio,
                        evidence={"ratio": ratio, "factor": factor, "reference_n": len(hist_avg)},
                    )
                )

    zr = m.get("zero_amount_ratio", 0.0)
    if zr > q.max_zero_amount_ratio:
        out.append(
            Finding(
                code="ZERO_AMOUNT_RECORDS",
                category=Category.QUALITY,
                severity=Severity.CRITICAL if zr > 3 * q.max_zero_amount_ratio else Severity.WARNING,
                message=(
                    f"Kayıtların {fmt.pct(zr, 1)}'i sıfır tutarlı (izin verilen en fazla "
                    f"{fmt.pct(q.max_zero_amount_ratio, 1)})."
                ),
                metric="zero_amount_ratio",
                observed=zr,
                upper=q.max_zero_amount_ratio,
            )
        )

    neg = m.get("negative_amount_count", 0.0)
    if q.forbid_negative_amounts and neg > 0:
        out.append(
            Finding(
                code="NEGATIVE_AMOUNTS",
                category=Category.QUALITY,
                severity=Severity.CRITICAL,
                message=f"{fmt.num(neg)} kayıtta negatif borç tutarı var.",
                metric="negative_amount_count",
                observed=neg,
                upper=0,
            )
        )

    dr = m.get("duplicate_record_ratio", 0.0)
    if dr > q.max_duplicate_record_ratio:
        out.append(
            Finding(
                code="DUPLICATE_RECORDS",
                category=Category.QUALITY,
                severity=Severity.WARNING,
                message=(
                    f"Dosya içindeki kayıtların {fmt.pct(dr, 1)}'i mükerrer (eşik "
                    f"{fmt.pct(q.max_duplicate_record_ratio, 1)})."
                ),
                metric="duplicate_record_ratio",
                observed=dr,
                upper=q.max_duplicate_record_ratio,
            )
        )
    return out
