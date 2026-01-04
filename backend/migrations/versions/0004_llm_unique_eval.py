"""Ensure at most one LLM explanation per evaluation.

Revision ID: 0004_llm_unique_eval
Revises: 0003_llm_pending
Create Date: 2026-01-04
"""

from __future__ import annotations

from alembic import op


revision = "0004_llm_unique_eval"
down_revision = "0003_llm_pending"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE llm_explanation ADD CONSTRAINT uq_llm_explanation_evaluation UNIQUE (evaluation_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE llm_explanation DROP CONSTRAINT IF EXISTS uq_llm_explanation_evaluation")


