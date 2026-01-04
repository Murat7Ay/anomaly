from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infra.db.models.calendar import BusinessCalendar, BusinessCalendarHoliday


class CalendarConflictError(Exception):
    pass


class CalendarNotFoundError(Exception):
    pass


class CalendarRepository:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create_calendar(self, *, name: str, description: str | None) -> BusinessCalendar:
        cal = BusinessCalendar(name=name, description=description)
        self._db.add(cal)
        try:
            self._db.commit()
        except IntegrityError as e:
            self._db.rollback()
            raise CalendarConflictError("calendar_name_conflict") from e
        self._db.refresh(cal)
        return cal

    def list_calendars(self) -> list[BusinessCalendar]:
        rows = self._db.execute(select(BusinessCalendar).order_by(BusinessCalendar.name)).scalars().all()
        return list(rows)

    def get_calendar(self, calendar_id: uuid.UUID) -> BusinessCalendar:
        cal = self._db.get(BusinessCalendar, calendar_id)
        if not cal:
            raise CalendarNotFoundError("calendar_not_found")
        return cal

    def add_holiday(
        self, *, calendar_id: uuid.UUID, holiday_date: date, name: str
    ) -> BusinessCalendarHoliday:
        _ = self.get_calendar(calendar_id)
        h = BusinessCalendarHoliday(calendar_id=calendar_id, holiday_date=holiday_date, name=name)
        self._db.add(h)
        try:
            self._db.commit()
        except IntegrityError as e:
            self._db.rollback()
            raise CalendarConflictError("holiday_conflict") from e
        self._db.refresh(h)
        return h

    def list_holidays(
        self, *, calendar_id: uuid.UUID, start_date: date, end_date: date
    ) -> list[BusinessCalendarHoliday]:
        _ = self.get_calendar(calendar_id)
        stmt = (
            select(BusinessCalendarHoliday)
            .where(
                and_(
                    BusinessCalendarHoliday.calendar_id == calendar_id,
                    BusinessCalendarHoliday.holiday_date >= start_date,
                    BusinessCalendarHoliday.holiday_date <= end_date,
                )
            )
            .order_by(BusinessCalendarHoliday.holiday_date.asc())
        )
        return list(self._db.execute(stmt).scalars().all())

    def holiday_dates_in_range(
        self, *, calendar_id: uuid.UUID, start_date: date, end_date: date
    ) -> set[date]:
        stmt = select(BusinessCalendarHoliday.holiday_date).where(
            and_(
                BusinessCalendarHoliday.calendar_id == calendar_id,
                BusinessCalendarHoliday.holiday_date >= start_date,
                BusinessCalendarHoliday.holiday_date <= end_date,
            )
        )
        return set(self._db.execute(stmt).scalars().all())


