from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infra.db.base import Base
from app.infra.db.models.common import CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin


class BusinessCalendar(Base, UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "business_calendar"

    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(512), nullable=True)

    holidays: Mapped[list["BusinessCalendarHoliday"]] = relationship(
        back_populates="calendar", cascade="all, delete-orphan"
    )


class BusinessCalendarHoliday(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    __tablename__ = "business_calendar_holiday"
    __table_args__ = (
        UniqueConstraint("calendar_id", "holiday_date", name="uq_calendar_holiday_date"),
    )

    calendar_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("business_calendar.id"), nullable=False, index=True
    )
    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)

    calendar: Mapped[BusinessCalendar] = relationship(back_populates="holidays")


