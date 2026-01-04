from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.domain.enums import RunType
from app.infra.repositories.dsl_repo import DslRuleSetRepository
from app.infra.repositories.institution_repo import InstitutionRepository
from app.infra.repositories.profile_repo import ProfileRepository
from app.application.detection.evaluation_service import EvaluationService


class ReplayMode(str, Enum):
    AS_OF = "AS_OF"
    LATEST = "LATEST"


@dataclass(frozen=True)
class ReplayRequest:
    mode: ReplayMode
    start_date: date
    end_date: date
    institution_id: uuid.UUID | None = None
    approved_cutoff_utc: datetime | None = None


class ReplayService:
    """
    Historical replay runner.

    - LATEST: uses currently effective approved profile/DSL versions for that date
    - AS_OF: uses versions that were already approved by approved_cutoff_utc (defaults to end-of-day in scheduler tz)
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._settings = get_settings()
        self._inst_repo = InstitutionRepository(db)
        self._profile_repo = ProfileRepository(db)
        self._dsl_repo = DslRuleSetRepository(db)
        self._eval_svc = EvaluationService(db)

    def replay(self, req: ReplayRequest) -> dict:
        if req.end_date < req.start_date:
            raise ValueError("invalid_date_range")

        if req.institution_id:
            institutions = [self._inst_repo.get(req.institution_id)]
        else:
            institutions = self._inst_repo.list_active()

        results = []
        d = req.start_date
        while d <= req.end_date:
            for inst in institutions:
                if req.mode == ReplayMode.LATEST:
                    pv = self._profile_repo.effective_version(institution_id=inst.id, as_of_date=d)
                    dv = self._dsl_repo.effective_version(institution_id=inst.id, as_of_date=d)
                    rt = RunType.REPLAY_LATEST
                else:
                    cutoff = req.approved_cutoff_utc or self._default_cutoff_for_date(d)
                    pv = self._profile_repo.effective_version_as_of(
                        institution_id=inst.id, as_of_date=d, approved_cutoff_utc=cutoff
                    )
                    dv = self._dsl_repo.effective_version_as_of(
                        institution_id=inst.id, as_of_date=d, approved_cutoff_utc=cutoff
                    )
                    rt = RunType.REPLAY_AS_OF

                r = self._eval_svc.evaluate_institution_day(
                    institution_id=inst.id,
                    as_of_date=d,
                    run_type=rt,
                    profile_version_override=pv,
                    dsl_version_override=dv,
                )
                results.append({"institution_id": str(inst.id), "as_of_date": d.isoformat(), "result": r})

            d = d + timedelta(days=1)

        return {"count": len(results), "results": results}

    def _default_cutoff_for_date(self, d: date) -> datetime:
        tz = ZoneInfo(self._settings.scheduler_timezone)
        local_dt = datetime.combine(d, time(23, 59, 59), tzinfo=tz)
        return local_dt.astimezone(timezone.utc)


