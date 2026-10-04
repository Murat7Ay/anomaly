"""Turkish public holidays (reference data seeded into the `holidays` table; editable in DB).

Religious holiday dates follow the Diyanet calendar; arife (eve) is a half day.
"""

from __future__ import annotations

from datetime import date, timedelta

from loadguard.domain.calendar import BusinessCalendar

_FIXED = [
    ((1, 1), "Yılbaşı"),
    ((4, 23), "Ulusal Egemenlik ve Çocuk Bayramı"),
    ((5, 1), "Emek ve Dayanışma Günü"),
    ((5, 19), "Atatürk'ü Anma, Gençlik ve Spor Bayramı"),
    ((7, 15), "Demokrasi ve Milli Birlik Günü"),
    ((8, 30), "Zafer Bayramı"),
    ((10, 29), "Cumhuriyet Bayramı"),
]
# (first day, number of days)
_RAMAZAN = {
    2024: (date(2024, 4, 10), 3),
    2025: (date(2025, 3, 30), 3),
    2026: (date(2026, 3, 20), 3),
    2027: (date(2027, 3, 9), 3),
    2028: (date(2028, 2, 26), 3),
}
_KURBAN = {
    2024: (date(2024, 6, 16), 4),
    2025: (date(2025, 6, 6), 4),
    2026: (date(2026, 5, 27), 4),
    2027: (date(2027, 5, 16), 4),
    2028: (date(2028, 5, 5), 4),
}


def tr_holidays(years: range = range(2024, 2029)) -> list[tuple[date, str, bool]]:
    """(date, name, is_half_day)."""
    out: list[tuple[date, str, bool]] = []
    for y in years:
        out += [(date(y, m, d), name, False) for (m, d), name in _FIXED]
        out.append((date(y, 10, 28), "Cumhuriyet Bayramı arifesi", True))
        for table, name in ((_RAMAZAN, "Ramazan Bayramı"), (_KURBAN, "Kurban Bayramı")):
            if y in table:
                first, n = table[y]
                out.append((first - timedelta(days=1), f"{name} arifesi", True))
                out += [(first + timedelta(days=i), f"{name} {i + 1}. gün", False) for i in range(n)]
    # Religious and national holidays can coincide (e.g. 19 May 2027): one row per date, full day wins.
    merged: dict[date, tuple[str, bool]] = {}
    for d, name, half in out:
        if d in merged:
            prev_name, prev_half = merged[d]
            merged[d] = (f"{prev_name} / {name}", prev_half and half)
        else:
            merged[d] = (name, half)
    return sorted((d, n, h) for d, (n, h) in merged.items())


def tr_calendar() -> BusinessCalendar:
    hs = tr_holidays()
    return BusinessCalendar(
        code="TR",
        holidays=frozenset(d for d, _, half in hs if not half),
        half_days=frozenset(d for d, _, half in hs if half),
    )
