from __future__ import annotations

from datetime import date, time

import pytest
from pydantic import ValidationError

from loadguard.domain.calendar import MonthPhase
from loadguard.domain.contract import Cadence, ContractSpec, DeliverySlot, HolidayShift
from loadguard.domain.schedule import expected_occurrences


def test_tr_calendar_knows_religious_and_fixed_holidays(cal):
    assert not cal.is_business_day(date(2026, 10, 29))  # Cumhuriyet Bayramı
    assert not cal.is_business_day(date(2026, 3, 20))  # Ramazan Bayramı
    assert not cal.is_business_day(date(2026, 5, 28))  # Kurban Bayramı
    assert date(2026, 10, 28) in cal.half_days
    assert cal.is_business_day(date(2026, 10, 28))


def test_month_phase(cal):
    assert cal.month_phase(date(2026, 9, 1)) == MonthPhase.START
    assert cal.month_phase(date(2026, 9, 15)) == MonthPhase.MID
    assert cal.month_phase(date(2026, 9, 30)) == MonthPhase.END


def _monthly(day: int, shift: HolidayShift) -> ContractSpec:
    return ContractSpec(
        slots=[
            DeliverySlot(
                key="m",
                label="Aylık",
                cadence=Cadence.MONTHLY,
                month_days=[day],
                holiday_shift=shift,
                window_start=time(8),
                deadline=time(14),
            )
        ]
    )


@pytest.mark.parametrize(
    ("shift", "expected"),
    [
        (HolidayShift.NEXT_BUSINESS_DAY, date(2026, 10, 30)),
        (HolidayShift.PREVIOUS_BUSINESS_DAY, date(2026, 10, 28)),
        (HolidayShift.NONE, date(2026, 10, 29)),
    ],
)
def test_monthly_slot_shifts_around_holiday(cal, shift, expected):
    occs = expected_occurrences(_monthly(29, shift), cal, date(2026, 10, 1), date(2026, 10, 31))
    assert [o.business_date for o in occs] == [expected]
    assert occs[0].nominal_date == date(2026, 10, 29)


def test_skip_shift_drops_occurrence(cal):
    assert (
        expected_occurrences(_monthly(29, HolidayShift.SKIP), cal, date(2026, 10, 1), date(2026, 10, 31))
        == []
    )


def test_business_day_slot_skips_weekends_and_holidays(cal, daily_spec):
    occs = expected_occurrences(daily_spec, cal, date(2026, 10, 26), date(2026, 11, 1))
    assert [o.business_date.day for o in occs] == [26, 27, 28, 30]


def test_deadline_is_converted_from_local_time(cal, daily_spec):
    occ = expected_occurrences(daily_spec, cal, date(2026, 10, 5), date(2026, 10, 5))[0]
    assert occ.deadline_utc.hour == 7  # 10:00 Istanbul == 07:00 UTC


def test_contract_validation_rejects_inconsistent_slot():
    with pytest.raises(ValidationError):
        DeliverySlot(key="w", label="x", cadence=Cadence.WEEKLY, window_start=time(8), deadline=time(9))
    with pytest.raises(ValidationError):
        DeliverySlot(
            key="d", label="x", cadence=Cadence.BUSINESS_DAYS, window_start=time(10), deadline=time(9)
        )


def test_spec_hash_is_stable_and_sensitive(daily_spec):
    same = ContractSpec.model_validate(daily_spec.canonical())
    assert same.spec_hash() == daily_spec.spec_hash()
    changed = daily_spec.model_copy(update={"timezone": "UTC"})
    assert changed.spec_hash() != daily_spec.spec_hash()
