"""Was the file delivered, and on time? Includes a predictive AT_RISK signal before the deadline."""

from __future__ import annotations

from zoneinfo import ZoneInfo

from loadguard.domain import fmt
from loadguard.domain.baseline import ArrivalProfile
from loadguard.domain.contract import Severity
from loadguard.domain.detectors.base import EvalContext
from loadguard.domain.model import Category, Finding, OccurrenceStatus
from loadguard.domain.schedule import local_date, local_minutes

AT_RISK_MARGIN_MIN = 15
DRIFT_MARGIN_MIN = 30


def detect_timeliness(
    ctx: EvalContext, arrival: ArrivalProfile | None
) -> tuple[OccurrenceStatus, list[Finding]]:
    tz = ctx.spec.timezone
    policy = ctx.spec.quality.unexpected_delivery

    if ctx.expected is None:
        if policy == "IGNORE" or not ctx.loads:
            return OccurrenceStatus.UNSCHEDULED, []
        first = ctx.loads[0]
        return OccurrenceStatus.UNSCHEDULED, [
            Finding(
                code="UNEXPECTED_DELIVERY",
                category=Category.TIMELINESS,
                severity=Severity(policy),
                message=(
                    f"Sözleşmede beklenmeyen bir günde ({ctx.business_date:%d.%m.%Y}) teslimat alındı "
                    f"({fmt.hhmm(local_minutes(first.received_at, tz))})."
                ),
                evidence={"received_at": first.received_at.isoformat()},
            )
        ]

    slot = ctx.slot
    assert slot is not None
    exp = ctx.expected
    deadline_min = local_minutes(exp.deadline_utc, tz)
    window_min = local_minutes(exp.window_start_utc, tz)
    base_ev = {
        "window_start": fmt.hhmm(window_min),
        "deadline": fmt.hhmm(deadline_min),
        "arrival_profile": arrival.to_dict() if arrival else None,
    }

    if not ctx.loads:
        if ctx.now >= exp.deadline_utc:
            return OccurrenceStatus.MISSING, [
                Finding(
                    code="MISSING_DELIVERY",
                    category=Category.TIMELINESS,
                    severity=Severity.CRITICAL,
                    message=(
                        f"'{slot.label}' dosyası son teslim saati {fmt.hhmm(deadline_min)}'e kadar gelmedi. "
                        "Müşteriler bu kurumun güncel borçlarını ödeyemiyor olabilir."
                    ),
                    evidence=base_ev,
                )
            ]
        same_day = local_date(ctx.now, tz) == ctx.business_date
        now_min = local_minutes(ctx.now, tz)
        if (
            arrival is not None
            and same_day
            and ctx.now >= exp.window_start_utc
            and now_min > arrival.p97_minutes + AT_RISK_MARGIN_MIN
        ):
            return OccurrenceStatus.AT_RISK, [
                Finding(
                    code="DELIVERY_AT_RISK",
                    category=Category.TIMELINESS,
                    severity=Severity.WARNING,
                    message=(
                        f"Dosya genellikle {fmt.hhmm(arrival.median_minutes)} civarında gelir "
                        f"(geçmiş teslimatların %97'si {fmt.hhmm(arrival.p97_minutes)}'den önce). "
                        f"Saat {fmt.hhmm(now_min)} itibarıyla henüz gelmedi; son teslim {fmt.hhmm(deadline_min)}. "
                        "Kurumla proaktif iletişim önerilir."
                    ),
                    score=(now_min - arrival.median_minutes),
                    evidence=base_ev | {"now": fmt.hhmm(now_min)},
                )
            ]
        return OccurrenceStatus.PENDING, []

    first = ctx.loads[0]
    arrived_min = local_minutes(first.received_at, tz)
    findings: list[Finding] = []
    if first.received_at > exp.deadline_utc:
        late_min = (first.received_at - exp.deadline_utc).total_seconds() / 60
        next_day = local_date(first.received_at, tz) > ctx.business_date
        findings.append(
            Finding(
                code="LATE_DELIVERY",
                category=Category.TIMELINESS,
                severity=Severity.CRITICAL if next_day else Severity.WARNING,
                message=(
                    f"'{slot.label}' dosyası son teslim saatinden {fmt.duration(late_min)} sonra geldi "
                    f"({first.received_at.astimezone(ZoneInfo(tz)):%d.%m} "
                    f"{fmt.hhmm(arrived_min)}, son teslim {fmt.hhmm(deadline_min)})."
                ),
                observed=late_min,
                evidence=base_ev | {"arrived": fmt.hhmm(arrived_min), "late_minutes": late_min},
            )
        )
        return OccurrenceStatus.LATE, findings

    if first.received_at < exp.window_start_utc and local_date(first.received_at, tz) == ctx.business_date:
        findings.append(
            Finding(
                code="EARLY_DELIVERY",
                category=Category.TIMELINESS,
                severity=Severity.INFO,
                message=(
                    f"Dosya beklenen pencereden önce geldi ({fmt.hhmm(arrived_min)}, pencere başlangıcı "
                    f"{fmt.hhmm(window_min)}). Eski/yanlış dosya olmadığı teyit edilebilir."
                ),
                evidence=base_ev | {"arrived": fmt.hhmm(arrived_min)},
            )
        )
    elif local_date(first.received_at, tz) < ctx.business_date:
        findings.append(
            Finding(
                code="EARLY_DELIVERY",
                category=Category.TIMELINESS,
                severity=Severity.INFO,
                message=f"Dosya beklenen günden önce geldi ({first.received_at:%d.%m.%Y}).",
                evidence=base_ev,
            )
        )
    elif arrival is not None and arrived_min > arrival.p97_minutes + DRIFT_MARGIN_MIN:
        findings.append(
            Finding(
                code="ARRIVAL_DRIFT",
                category=Category.TIMELINESS,
                severity=Severity.INFO,
                message=(
                    f"Dosya süresinde geldi ancak alışılmıştan geç ({fmt.hhmm(arrived_min)}; "
                    f"olağan {fmt.hhmm(arrival.median_minutes)}). Eğilim sürerse son teslim riski oluşabilir."
                ),
                observed=float(arrived_min),
                expected=arrival.median_minutes,
                upper=arrival.p97_minutes,
                evidence=base_ev | {"arrived": fmt.hhmm(arrived_min)},
            )
        )
    return OccurrenceStatus.RECEIVED, findings
