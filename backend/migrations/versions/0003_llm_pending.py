"""Add PENDING status to llm_status enum.

Revision ID: 0003_llm_pending
Revises: 0002_ml_artifact
Create Date: 2026-01-04
"""

from __future__ import annotations

from alembic import op


revision = "0003_llm_pending"
down_revision = "0002_ml_artifact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres: add enum value
    op.execute("ALTER TYPE llm_status ADD VALUE IF NOT EXISTS 'PENDING'")


def downgrade() -> None:
    # Postgres enums can't easily drop values; no-op downgrade.
    pass


