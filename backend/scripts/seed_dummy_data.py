#!/usr/bin/env python3
"""
Seed dummy data for development/testing.
Run: python -m scripts.seed_dummy_data
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session

from app.domain.enums import ShiftRule
from app.domain.profile.config import (
    Cadence,
    DailyKind,
    InstitutionProfileConfig,
    MaturityPolicy,
    MethodPolicy,
    OccurrenceSpec,
    ScheduleSpec,
    StatsMethod,
    VolumeBehavior,
    VolumeModel,
)
from app.infra.db.session import db_session
from app.infra.repositories.calendar_repo import CalendarRepository
from app.infra.repositories.institution_repo import InstitutionRepository
from app.application.profile.profile_service import ProfileService
from app.application.dsl.dsl_service import DslService


def seed_data(db: Session) -> None:
    print("Seeding dummy data...")

    # 1. Create calendar
    print("  Creating calendar...")
    cal_repo = CalendarRepository(db)
    try:
        cal = cal_repo.create_calendar(
            name="TR Business Calendar",
            description="Turkey business days calendar"
        )
        print(f"    [OK] Calendar created: {cal.id} - {cal.name}")
    except Exception as e:
        # Calendar might already exist, try to get it
        cals = cal_repo.list_calendars()
        if cals:
            cal = cals[0]
            print(f"    [OK] Using existing calendar: {cal.id} - {cal.name}")
        else:
            raise

    # Add some holidays
    today = date.today()
    holidays = [
        (today + timedelta(days=30), "Test Holiday 1"),
        (today + timedelta(days=60), "Test Holiday 2"),
    ]
    for h_date, h_name in holidays:
        try:
            cal_repo.add_holiday(calendar_id=cal.id, holiday_date=h_date, name=h_name)
            print(f"    [OK] Holiday added: {h_date} - {h_name}")
        except Exception:
            pass  # Already exists

    # 2. Create institutions
    print("  Creating institutions...")
    inst_repo = InstitutionRepository(db)
    
    institutions_data = [
        {
            "external_code": "BILLER001",
            "display_name": "Örnek Fatura Kurumu 1",
            "default_timezone": "Europe/Istanbul",
            "default_calendar_id": cal.id,
        },
        {
            "external_code": "BILLER002",
            "display_name": "Örnek Fatura Kurumu 2",
            "default_timezone": "Europe/Istanbul",
            "default_calendar_id": cal.id,
        },
        {
            "external_code": "BILLER003",
            "display_name": "Günlük Yüklenen Kurum",
            "default_timezone": "Europe/Istanbul",
            "default_calendar_id": cal.id,
        },
    ]

    institutions = []
    for inst_data in institutions_data:
        try:
            inst = inst_repo.create(**inst_data)
            institutions.append(inst)
            print(f"    [OK] Institution created: {inst.external_code} - {inst.display_name}")
        except Exception as e:
            # Try to get existing
            existing = inst_repo.list()
            inst = next((i for i in existing if i.external_code == inst_data["external_code"]), None)
            if inst:
                institutions.append(inst)
                print(f"    [OK] Using existing institution: {inst.external_code}")
            else:
                print(f"    [ERROR] Failed to create {inst_data['external_code']}: {e}")

    if not institutions:
        print("    [WARN] No institutions available!")
        return

    # 3. Create profiles for each institution
    print("  Creating profiles...")
    profile_service = ProfileService(db)
    actor_id = "system-seed"

    for inst in institutions:
        try:
            # Create a profile config
            first_seen = date.today() - timedelta(days=200)  # 200 days ago
            
            # Build occurrence spec
            if inst.external_code == "BILLER001":
                occurrence = OccurrenceSpec(
                    occurrence_id="main_load",
                    cadence=Cadence.WEEKLY,
                    shift_rule=ShiftRule.NEXT_BUSINESS_DAY,
                    expected_by_run="PM_1400",
                    grace_minutes=60,
                    max_late_business_days=1,
                    days_of_week_iso=[1, 3, 5],  # Mon, Wed, Fri
                )
            elif inst.external_code == "BILLER003":
                occurrence = OccurrenceSpec(
                    occurrence_id="main_load",
                    cadence=Cadence.DAILY,
                    shift_rule=ShiftRule.NEXT_BUSINESS_DAY,
                    expected_by_run="PM_1400",
                    grace_minutes=60,
                    max_late_business_days=1,
                    daily_kind=DailyKind.BUSINESS_DAYS,
                )
            else:
                occurrence = OccurrenceSpec(
                    occurrence_id="main_load",
                    cadence=Cadence.WEEKLY,
                    shift_rule=ShiftRule.NEXT_BUSINESS_DAY,
                    expected_by_run="PM_1400",
                    grace_minutes=60,
                    max_late_business_days=1,
                    days_of_week_iso=[5],  # Friday
                )

            config = InstitutionProfileConfig(
                timezone="Europe/Istanbul",
                calendar_id=cal.id,
                maturity_policy=MaturityPolicy(
                    first_seen_date=first_seen,
                    stats_enabled_after_days=180,
                    ml_enabled_after_days=180,
                    min_expected_loads_for_stats=12,
                    min_expected_loads_for_ml=24,
                ),
                schedule=ScheduleSpec(occurrences=[occurrence]),
                volume_models=[
                    VolumeModel(
                        metric_id="debt_item_count",
                        behavior=VolumeBehavior.STABLE,
                        method_policy=MethodPolicy(
                            primary_method=StatsMethod.PERCENTILE,
                            params={"p_low": 0.05, "p_high": 0.95},
                            fallback_order=[StatsMethod.IQR, StatsMethod.Z_SCORE],
                            window_months=6,
                            min_n=12,
                        ),
                        segment_by_occurrence=True,
                    )
                ],
            )

            # Create draft
            effective_from = date.today() - timedelta(days=30)
            draft = profile_service.create_draft(
                institution_id=inst.id,
                effective_from=effective_from,
                created_by=actor_id,
                config=config,
            )
            print(f"    [OK] Profile draft created for {inst.external_code}: v{draft.version_num}")

            # Approve it
            profile_service.approve_version(
                institution_id=inst.id,
                version_id=draft.id,
                approved_by=actor_id,
                approval_reason="Initial seed data",
            )
            print(f"    [OK] Profile approved for {inst.external_code}")

        except Exception as e:
            print(f"    [ERROR] Failed to create profile for {inst.external_code}: {e}")

    # 4. Create DSL rules for first institution
    print("  Creating DSL rules...")
    dsl_service = DslService(db)
    
    if institutions:
        inst = institutions[0]
        try:
            rules_json = {
                "schema_version": 1,
                "rules": [
                    {
                        "id": "no_data_pm",
                        "enabled": True,
                        "description": "Expect load by PM run; if missing => NO_DATA",
                        "type": "EXPECT_LOAD_BY_RUN",
                        "anomaly_type": "NO_DATA",
                        "message": "Expected load by PM but no data present",
                        "params": {
                            "schedule": {"source": "PROFILE"},
                            "run": "PM_1400",
                            "include_collisions": True,
                        },
                    },
                    {
                        "id": "volume_spike",
                        "enabled": True,
                        "description": "Debt item count > 2x median",
                        "type": "VOLUME_THRESHOLD",
                        "anomaly_type": "VOLUME_SPIKE",
                        "message": "Debt item count exceeds 2x median",
                        "params": {
                            "metric_id": "debt_item_count",
                            "threshold_multiplier": 2.0,
                            "use_median": True,
                        },
                    },
                ],
            }

            effective_from = date.today() - timedelta(days=30)
            draft = dsl_service.create_draft(
                institution_id=inst.id,
                effective_from=effective_from,
                created_by=actor_id,
                rules_json=rules_json,
            )
            print(f"    [OK] DSL draft created for {inst.external_code}: v{draft.version_num}")

            # Validate
            dsl_service.validate_existing_draft(
                institution_id=inst.id,
                version_id=draft.id,
                actor_id=actor_id,
            )
            print(f"    [OK] DSL validated for {inst.external_code}")

            # Approve
            dsl_service.approve_version(
                institution_id=inst.id,
                version_id=draft.id,
                approved_by=actor_id,
                approval_reason="Initial seed data",
            )
            print(f"    [OK] DSL approved for {inst.external_code}")

        except Exception as e:
            print(f"    [ERROR] Failed to create DSL for {inst.external_code}: {e}")

    print("[OK] Seeding complete!")


if __name__ == "__main__":
    db_gen = db_session()
    db = next(db_gen)
    try:
        seed_data(db)
        db.commit()
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Error: {e}")
        raise
    finally:
        db.close()

