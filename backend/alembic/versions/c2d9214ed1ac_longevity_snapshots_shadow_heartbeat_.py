"""longevity: decision snapshots, shadow results, worker heartbeat, audit hash chain, append-only guards

Revision ID: c2d9214ed1ac
Revises: 9873bb945da0
Create Date: 2026-10-04 04:51:44.844593
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c2d9214ed1ac"
down_revision: str | None = "9873bb945da0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY = ("evaluations", "audit_log", "input_snapshots")


def _row_hash(prev: str | None, at: str, actor: str, action: str, etype: str, eid: str, details: object) -> str:
    # Frozen copy of services.common.audit_row_hash: migrations must not depend on mutable app code.
    body = json.dumps(
        {"at": at, "actor": actor, "action": action, "entity_type": etype, "entity_id": eid, "details": details},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(f"{prev or ''}|{body}".encode()).hexdigest()


def upgrade() -> None:
    op.create_table(
        "input_snapshots",
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("sha256", name="pk_input_snapshots"),
    )
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(length=96), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_beat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_tick_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("worker_id", name="pk_worker_heartbeats"),
    )
    op.create_table(
        "shadow_results",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("occurrence_id", sa.Uuid(), nullable=False),
        sa.Column("challenger", sa.String(length=48), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("max_severity", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(["occurrence_id"], ["occurrences.id"], name="fk_shadow_results_occurrence_id"),
        sa.PrimaryKeyConstraint("id", name="pk_shadow_results"),
        sa.UniqueConstraint("occurrence_id", "challenger", name="uq_shadow_results_occurrence_challenger"),
    )
    op.create_index("ix_shadow_results_occurrence_id", "shadow_results", ["occurrence_id"])

    op.add_column("evaluations", sa.Column("snapshot_sha", sa.String(length=64), nullable=True))
    op.create_index("ix_evaluations_snapshot_sha", "evaluations", ["snapshot_sha"])
    op.create_foreign_key(
        "fk_evaluations_snapshot_sha", "evaluations", "input_snapshots", ["snapshot_sha"], ["sha256"]
    )

    # Audit hash chain, backfilled for existing rows in id order.
    op.add_column("audit_log", sa.Column("prev_hash", sa.String(length=64), nullable=True))
    op.add_column("audit_log", sa.Column("row_hash", sa.String(length=64), nullable=False, server_default=""))
    conn = op.get_bind()
    prev = None
    rows = conn.execute(
        sa.text("select id, at, actor, action, entity_type, entity_id, details from audit_log order by id")
    ).all()
    for r in rows:
        h = _row_hash(prev, r.at.astimezone(UTC).isoformat(), r.actor, r.action, r.entity_type, r.entity_id, r.details)
        conn.execute(
            sa.text("update audit_log set prev_hash=:p, row_hash=:h where id=:i"), {"p": prev, "h": h, "i": r.id}
        )
        prev = h

    # Append-only enforced by the database itself, not only by application discipline.
    op.execute(
        """
        create or replace function lg_forbid_mutation() returns trigger language plpgsql as $$
        begin
          raise exception 'table % is append-only (% not allowed)', tg_table_name, tg_op
            using errcode = 'insufficient_privilege';
        end $$;
        """
    )
    for t in APPEND_ONLY:
        op.execute(
            f"create trigger trg_{t}_append_only before update or delete on {t} "
            f"for each row execute function lg_forbid_mutation()"
        )


def downgrade() -> None:
    for t in APPEND_ONLY:
        op.execute(f"drop trigger if exists trg_{t}_append_only on {t}")
    op.execute("drop function if exists lg_forbid_mutation()")
    op.drop_column("audit_log", "row_hash")
    op.drop_column("audit_log", "prev_hash")
    op.drop_constraint("fk_evaluations_snapshot_sha", "evaluations", type_="foreignkey")
    op.drop_index("ix_evaluations_snapshot_sha", table_name="evaluations")
    op.drop_column("evaluations", "snapshot_sha")
    op.drop_index("ix_shadow_results_occurrence_id", table_name="shadow_results")
    op.drop_table("shadow_results")
    op.drop_table("worker_heartbeats")
    op.drop_table("input_snapshots")
