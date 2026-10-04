"""The advisory AI must never get to invent numbers or write an invalid contract."""

from __future__ import annotations

from loadguard.ai.grounding import check_grounding, numbers_in


def test_turkish_number_parsing():
    assert numbers_in("Beklenen 182.400 kayıt, gözlenen 61.200 (−%66); tutar 1.234.567,89 TL") == [
        182400.0,
        61200.0,
        66.0,
        1234567.89,
    ]


def test_grounded_text_passes():
    facts = {"findings": [{"observed": 61200.0, "expected": 182400.0, "message": "beklenenden %66 düşük"}]}
    g = check_grounding(["Kayıt sayısı 61.200, beklenen 182.400; yaklaşık %66 düşüş."], facts)
    assert g["status"] == "GROUNDED"


def test_invented_number_is_flagged():
    facts = {"findings": [{"observed": 61200.0, "expected": 182400.0}]}
    g = check_grounding(["Eşik 150.000 olarak uygulandı."], facts)
    assert g["status"] == "UNVERIFIED_NUMBERS" and 150000.0 in g["unverified"]


def test_small_generic_numbers_are_ignored():
    g = check_grounding(["2 iş günü içinde kurumla görüşün; 3 adım izleyin."], {})
    assert g["status"] == "GROUNDED"


def test_long_decimals_are_one_number():
    # Regression: a model echoing a raw float was split into two "numbers" and falsely flagged.
    assert numbers_in("mükerrer kayıt oranı 0.0016508805567020004.") == [0.0016508805567020004]
    g = check_grounding(["oran 0.0016508805567020004"], {"ratio": 0.0016508805567020004})
    assert g["status"] == "GROUNDED"
    assert numbers_in("tutar 144.355 TL") == [144355.0]
