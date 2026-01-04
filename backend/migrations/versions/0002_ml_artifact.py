"""Add ML artifact storage.

Revision ID: 0002_ml_artifact
Revises: 0001_initial
Create Date: 2026-01-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0002_ml_artifact"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "institution_ml_artifact",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institution.id"),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column(
            "profile_config_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institution_profile_config_version.id"),
            nullable=False,
        ),
        sa.Column(
            "algorithm_version",
            sa.String(length=64),
            server_default=sa.text("'ml_mahalanobis_v1'"),
            nullable=False,
        ),
        sa.Column("artifact_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "artifact_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "institution_id",
            "as_of_date",
            "profile_config_version_id",
            "algorithm_version",
            name="uq_ml_artifact",
        ),
    )
    op.create_index("ix_institution_ml_artifact_institution_id", "institution_ml_artifact", ["institution_id"])
    op.create_index("ix_institution_ml_artifact_as_of_date", "institution_ml_artifact", ["as_of_date"])
    op.create_index(
        "ix_institution_ml_artifact_profile_config_version_id",
        "institution_ml_artifact",
        ["profile_config_version_id"],
    )
    op.create_index(
        "ix_institution_ml_artifact_artifact_hash", "institution_ml_artifact", ["artifact_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_institution_ml_artifact_artifact_hash", table_name="institution_ml_artifact")
    op.drop_index(
        "ix_institution_ml_artifact_profile_config_version_id", table_name="institution_ml_artifact"
    )
    op.drop_index("ix_institution_ml_artifact_as_of_date", table_name="institution_ml_artifact")
    op.drop_index("ix_institution_ml_artifact_institution_id", table_name="institution_ml_artifact")
    op.drop_table("institution_ml_artifact")


