from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.enums import LoadSource
from app.infra.db.base import Base
from app.infra.db.models.common import CreatedAtMixin, UuidPrimaryKeyMixin


class LoadBatch(Base, UuidPrimaryKeyMixin, CreatedAtMixin):
    """
    Canonical ingestion record for a single delivered load (API pull, FTP file, etc).

    The evaluation pipeline consumes *aggregated daily metrics* derived from one or more LoadBatch rows.
    """

    __tablename__ = "load_batch"

    institution_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("institution.id"), nullable=False, index=True
    )
    source: Mapped[LoadSource] = mapped_column(Enum(LoadSource, name="load_source"), nullable=False)

    received_at_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    institution_local_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    reference: Mapped[str | None] = mapped_column(String(256), nullable=True)  # file name, request id, etc.

    debt_item_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_debt_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 4), nullable=True)
    unique_customer_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    metrics_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    raw_metadata_json: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )


