from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import InternalAuthDep, get_db
from app.application.detection.replay_service import ReplayMode, ReplayRequest, ReplayService

router = APIRouter(prefix="/replay", tags=["replay"])


class ReplayRunRequest(BaseModel):
    mode: ReplayMode = Field(default=ReplayMode.LATEST)
    start_date: date
    end_date: date
    institution_id: uuid.UUID | None = None
    approved_cutoff_utc: datetime | None = None


@router.post("", status_code=status.HTTP_200_OK, dependencies=[InternalAuthDep])
def run_replay(req: ReplayRunRequest, db: Session = Depends(get_db)) -> dict:
    svc = ReplayService(db)
    try:
        return svc.replay(
            ReplayRequest(
                mode=req.mode,
                start_date=req.start_date,
                end_date=req.end_date,
                institution_id=req.institution_id,
                approved_cutoff_utc=req.approved_cutoff_utc,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


