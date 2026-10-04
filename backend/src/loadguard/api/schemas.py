from __future__ import annotations

from datetime import date, datetime

from pydantic import AwareDatetime, BaseModel, Field

from loadguard.domain.contract import ContractSpec


class LoginIn(BaseModel):
    username: str


class LoadIn(BaseModel):
    """Summary produced by the integration edge after parsing a debt file. The raw file never reaches us."""

    institution_code: str = Field(max_length=32)
    external_id: str = Field(max_length=128, description="Idempotency key, e.g. SFTP path + checksum")
    received_at: AwareDatetime
    content_hash: str = Field(min_length=8, max_length=128)
    record_count: int = Field(ge=0)
    total_amount: float
    customer_count: int = Field(ge=0)
    zero_amount_count: int = Field(default=0, ge=0)
    negative_amount_count: int = Field(default=0, ge=0)
    duplicate_record_count: int = Field(default=0, ge=0)
    max_amount: float | None = None
    file_name: str | None = Field(default=None, max_length=255)
    slot_hint: str | None = Field(default=None, max_length=48)
    source: str = Field(default="API", pattern="^(API|SFTP|SIM)$")


class AckIn(BaseModel):
    pass


class AssignIn(BaseModel):
    assignee: str | None


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ResolveIn(BaseModel):
    resolution: str
    note: str | None = Field(default=None, max_length=4000)


class DraftIn(BaseModel):
    spec: ContractSpec
    effective_from: date
    change_note: str | None = Field(default=None, max_length=2000)
    origin: str = Field(default="MANUAL", pattern="^(MANUAL|INFERRED|TUNING|AI_ASSIST)$")


class DecisionIn(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class BacktestIn(BaseModel):
    spec: ContractSpec
    days: int = Field(default=90, ge=14, le=365)


class AssistIn(BaseModel):
    instruction: str = Field(min_length=3, max_length=2000)
    base_spec: ContractSpec | None = None


class SuppressionIn(BaseModel):
    institution_id: str | None = None
    starts_at: AwareDatetime
    ends_at: AwareDatetime
    reason: str = Field(min_length=3, max_length=500)


class InstitutionIn(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Z0-9_-]+$")
    name: str = Field(min_length=2, max_length=200)
    sector: str = Field(max_length=32)
    tier: int = Field(ge=1, le=3)
    contact_email: str | None = None
    notes: str | None = None


class InstitutionPatch(BaseModel):
    name: str | None = None
    tier: int | None = Field(default=None, ge=1, le=3)
    active: bool | None = None
    contact_email: str | None = None
    notes: str | None = None


def iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None
