"""Turkish formatting for human-facing messages. Messages are generated deterministically from evidence."""

from __future__ import annotations

METRIC_LABELS = {
    "record_count": "Kayıt sayısı",
    "total_amount": "Toplam borç tutarı",
    "customer_count": "Müşteri sayısı",
    "avg_amount": "Ortalama borç tutarı",
    "zero_amount_ratio": "Sıfır tutarlı kayıt oranı",
    "negative_amount_count": "Negatif tutarlı kayıt sayısı",
    "duplicate_record_ratio": "Mükerrer kayıt oranı",
    "max_amount": "En yüksek borç tutarı",
}

MONEY_METRICS = {"total_amount", "avg_amount", "max_amount"}
RATIO_METRICS = {"zero_amount_ratio", "duplicate_record_ratio"}


def num(v: float, digits: int = 0) -> str:
    s = f"{v:,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def money(v: float) -> str:
    return f"{num(v, 2 if abs(v) < 1000 else 0)} TL"


def pct(v: float, digits: int = 0) -> str:
    return f"%{num(v * 100, digits)}"


def metric_value(metric: str, v: float) -> str:
    if metric in MONEY_METRICS:
        return money(v)
    if metric in RATIO_METRICS:
        return pct(v, 1)
    return num(v)


def hhmm(minutes: float) -> str:
    m = round(minutes)
    return f"{m // 60:02d}:{m % 60:02d}"


def duration(minutes: float) -> str:
    m = round(minutes)
    if m < 60:
        return f"{m} dk"
    h, r = divmod(m, 60)
    if h < 24:
        return f"{h} sa {r} dk" if r else f"{h} sa"
    d, h = divmod(h, 24)
    return f"{d} gün {h} sa" if h else f"{d} gün"
