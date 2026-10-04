"""Grounding check: every number an AI text states must exist in the facts it was given.

LLMs paraphrase well and invent numbers confidently. In an operational control function an invented
threshold is worse than no text, so unverifiable numbers are surfaced to the reader.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any

_NUM = re.compile(r"(?<![\w])[-+]?\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|[-+]?\d+(?:[.,]\d+)?")
SMALL_INT_FREE = 31  # days, hours, list counts... too generic to verify meaningfully


def _parse(tok: str) -> float | None:
    t = tok.replace(" ", "")
    if re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+(?:,\d+)?", t):  # Turkish thousands: 1.234.567,89
        t = t.replace(".", "").replace(",", ".")
    elif "," in t and "." not in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def numbers_in(text: str) -> list[float]:
    return [v for v in (_parse(m.group()) for m in _NUM.finditer(text)) if v is not None]


def _walk(obj: Any) -> Iterable[float]:
    if isinstance(obj, bool):
        return
    if isinstance(obj, int | float):
        yield float(obj)
    elif isinstance(obj, str):
        yield from numbers_in(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list | tuple):
        for v in obj:
            yield from _walk(v)


def _close(a: float, b: float) -> bool:
    if a == b:
        return True
    for cand in (b, b * 100, b / 100):  # ratios stated as percentages and vice versa
        if cand and abs(a - cand) / max(abs(cand), 1e-9) <= 0.015:
            return True
    return abs(a) >= 1000 and math.isclose(a, b, rel_tol=0.02)


def check_grounding(texts: list[str], facts: dict[str, Any]) -> dict[str, Any]:
    known = list(_walk(facts))
    stated = [n for t in texts for n in numbers_in(t)]
    unverified = sorted(
        {n for n in stated if abs(n) > SMALL_INT_FREE and not any(_close(n, k) for k in known)}
    )
    return {
        "status": "GROUNDED" if not unverified else "UNVERIFIED_NUMBERS",
        "checked_numbers": len([n for n in stated if abs(n) > SMALL_INT_FREE]),
        "unverified": unverified[:20],
    }
