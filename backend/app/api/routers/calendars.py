from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import InternalAuthDep, get_db
from app.infra.repositories.calendar_repo import (
    CalendarConflictError,
    CalendarNotFoundError,
    CalendarRepository,
)

router = APIRouter(prefix="/calendars", tags=["calendars"])


class CalendarCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)


class CalendarResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None


class HolidayCreateRequest(BaseModel):
    holiday_date: date
    name: str = Field(min_length=1, max_length=256)


class HolidayResponse(BaseModel):
    id: uuid.UUID
    holiday_date: date
    name: str


@router.post("", response_model=CalendarResponse, status_code=status.HTTP_201_CREATED, dependencies=[InternalAuthDep])
def create_calendar(req: CalendarCreateRequest, db: Session = Depends(get_db)) -> CalendarResponse:
    repo = CalendarRepository(db)
    try:
        cal = repo.create_calendar(name=req.name, description=req.description)
    except CalendarConflictError:
        raise HTTPException(status_code=409, detail="calendar_name_conflict")
    return CalendarResponse(id=cal.id, name=cal.name, description=cal.description)


@router.get("", response_model=list[CalendarResponse], dependencies=[InternalAuthDep])
def list_calendars(db: Session = Depends(get_db)) -> list[CalendarResponse]:
    repo = CalendarRepository(db)
    cals = repo.list_calendars()
    return [CalendarResponse(id=c.id, name=c.name, description=c.description) for c in cals]


@router.get("/{calendar_id}", response_model=CalendarResponse, dependencies=[InternalAuthDep])
def get_calendar(calendar_id: uuid.UUID, db: Session = Depends(get_db)) -> CalendarResponse:
    repo = CalendarRepository(db)
    try:
        cal = repo.get_calendar(calendar_id)
    except CalendarNotFoundError:
        raise HTTPException(status_code=404, detail="calendar_not_found")
    return CalendarResponse(id=cal.id, name=cal.name, description=cal.description)


@router.post(
    "/{calendar_id}/holidays",
    response_model=HolidayResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[InternalAuthDep],
)
def add_holiday(calendar_id: uuid.UUID, req: HolidayCreateRequest, db: Session = Depends(get_db)) -> HolidayResponse:
    repo = CalendarRepository(db)
    try:
        h = repo.add_holiday(calendar_id=calendar_id, holiday_date=req.holiday_date, name=req.name)
    except CalendarNotFoundError:
        raise HTTPException(status_code=404, detail="calendar_not_found")
    except CalendarConflictError:
        raise HTTPException(status_code=409, detail="holiday_conflict")
    return HolidayResponse(id=h.id, holiday_date=h.holiday_date, name=h.name)


@router.get("/{calendar_id}/holidays", response_model=list[HolidayResponse], dependencies=[InternalAuthDep])
def list_holidays(
    calendar_id: uuid.UUID,
    start: date,
    end: date,
    db: Session = Depends(get_db),
) -> list[HolidayResponse]:
    if end < start:
        raise HTTPException(status_code=400, detail="invalid_date_range")
    repo = CalendarRepository(db)
    try:
        holidays = repo.list_holidays(calendar_id=calendar_id, start_date=start, end_date=end)
    except CalendarNotFoundError:
        raise HTTPException(status_code=404, detail="calendar_not_found")
    return [HolidayResponse(id=h.id, holiday_date=h.holiday_date, name=h.name) for h in holidays]


