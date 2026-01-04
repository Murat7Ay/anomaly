"""Initial schema.

Revision ID: 0001_initial
Revises: 
Create Date: 2026-01-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- Enums ---
    sa.Enum("API", "FTP", name="load_source").create(op.get_bind(), checkfirst=True)
    sa.Enum("DRAFT", "APPROVED", "RETIRED", name="version_status").create(
        op.get_bind(), checkfirst=True
    )
    sa.Enum(
        "AM_0900",
        "PM_1400",
        "MANUAL",
        "REPLAY_AS_OF",
        "REPLAY_LATEST",
        name="run_type",
    ).create(op.get_bind(), checkfirst=True)
    sa.Enum("NONE", "WARNING", "CRITICAL", name="severity").create(op.get_bind(), checkfirst=True)
    sa.Enum("DSL", "STATS", "ML", name="detection_layer").create(op.get_bind(), checkfirst=True)
    sa.Enum("SUCCESS", "FAILED", "SKIPPED", name="llm_status").create(op.get_bind(), checkfirst=True)
    sa.Enum("PENDING", "SENT", "FAILED", name="notification_status").create(
        op.get_bind(), checkfirst=True
    )
    sa.Enum("EMAIL", name="notification_channel").create(op.get_bind(), checkfirst=True)

    load_source_enum = postgresql.ENUM("API", "FTP", name="load_source", create_type=False)
    version_status_enum = postgresql.ENUM(
        "DRAFT", "APPROVED", "RETIRED", name="version_status", create_type=False
    )
    run_type_enum = postgresql.ENUM(
        "AM_0900",
        "PM_1400",
        "MANUAL",
        "REPLAY_AS_OF",
        "REPLAY_LATEST",
        name="run_type",
        create_type=False,
    )
    severity_enum = postgresql.ENUM("NONE", "WARNING", "CRITICAL", name="severity", create_type=False)
    detection_layer_enum = postgresql.ENUM("DSL", "STATS", "ML", name="detection_layer", create_type=False)
    llm_status_enum = postgresql.ENUM("SUCCESS", "FAILED", "SKIPPED", name="llm_status", create_type=False)
    notification_status_enum = postgresql.ENUM(
        "PENDING", "SENT", "FAILED", name="notification_status", create_type=False
    )
    notification_channel_enum = postgresql.ENUM("EMAIL", name="notification_channel", create_type=False)

    # --- Calendars ---
    op.create_table(
        "business_calendar",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(length=512), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_business_calendar_name", "business_calendar", ["name"], unique=True)

    op.create_table(
        "business_calendar_holiday",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "calendar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business_calendar.id"),
            nullable=False,
        ),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("calendar_id", "holiday_date", name="uq_calendar_holiday_date"),
    )
    op.create_index(
        "ix_business_calendar_holiday_calendar_id", "business_calendar_holiday", ["calendar_id"]
    )
    op.create_index(
        "ix_business_calendar_holiday_holiday_date",
        "business_calendar_holiday",
        ["holiday_date"],
    )

    # --- Institutions ---
    op.create_table(
        "institution",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("external_code", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=256), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("default_timezone", sa.String(length=64), nullable=True),
        sa.Column(
            "default_calendar_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("business_calendar.id"),
            nullable=True,
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_institution_external_code", "institution", ["external_code"], unique=True)

    # --- Ingestion ---
    op.create_table(
        "load_batch",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institution.id"),
            nullable=False,
        ),
        sa.Column("source", load_source_enum, nullable=False),
        sa.Column("received_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("institution_local_date", sa.Date(), nullable=False),
        sa.Column("reference", sa.String(length=256), nullable=True),
        sa.Column("debt_item_count", sa.Integer(), nullable=True),
        sa.Column("total_debt_amount", sa.Numeric(24, 4), nullable=True),
        sa.Column("unique_customer_count", sa.Integer(), nullable=True),
        sa.Column("metrics_json", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column(
            "raw_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_load_batch_institution_id", "load_batch", ["institution_id"])
    op.create_index("ix_load_batch_received_at_utc", "load_batch", ["received_at_utc"])
    op.create_index("ix_load_batch_institution_local_date", "load_batch", ["institution_local_date"])

    # --- Institution Profiles ---
    op.create_table(
        "institution_profile_config_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institution.id"),
            nullable=False,
        ),
        sa.Column("version_num", sa.Integer(), nullable=False),
        sa.Column("status", version_status_enum, nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("config_hash", sa.String(length=128), nullable=False),
        sa.Column("config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("approved_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("approval_reason", sa.String(length=512), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("institution_id", "version_num", name="uq_profile_versionnum"),
    )
    op.create_index(
        "ix_institution_profile_config_version_institution_id",
        "institution_profile_config_version",
        ["institution_id"],
    )
    op.create_index(
        "ix_institution_profile_config_version_status",
        "institution_profile_config_version",
        ["status"],
    )
    op.create_index(
        "ix_institution_profile_config_version_effective_from",
        "institution_profile_config_version",
        ["effective_from"],
    )
    op.create_index(
        "ix_institution_profile_config_version_effective_to",
        "institution_profile_config_version",
        ["effective_to"],
    )
    op.create_index(
        "ix_institution_profile_config_version_config_hash",
        "institution_profile_config_version",
        ["config_hash"],
    )

    op.create_table(
        "institution_profile_stats_snapshot",
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
        sa.Column("algorithm_version", sa.String(length=64), server_default=sa.text("'v1'"), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=128), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_cutoff_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "institution_id",
            "as_of_date",
            "profile_config_version_id",
            name="uq_profile_stats_snapshot",
        ),
    )
    op.create_index(
        "ix_institution_profile_stats_snapshot_institution_id",
        "institution_profile_stats_snapshot",
        ["institution_id"],
    )
    op.create_index(
        "ix_institution_profile_stats_snapshot_as_of_date",
        "institution_profile_stats_snapshot",
        ["as_of_date"],
    )
    op.create_index(
        "ix_institution_profile_stats_snapshot_profile_config_version_id",
        "institution_profile_stats_snapshot",
        ["profile_config_version_id"],
    )
    op.create_index(
        "ix_institution_profile_stats_snapshot_snapshot_hash",
        "institution_profile_stats_snapshot",
        ["snapshot_hash"],
    )

    # --- DSL rule sets ---
    op.create_table(
        "dsl_rule_set_version",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institution.id"),
            nullable=False,
        ),
        sa.Column("version_num", sa.Integer(), nullable=False),
        sa.Column("status", version_status_enum, nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("schema_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("rules_hash", sa.String(length=128), nullable=False),
        sa.Column("rules_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("compiled_hash", sa.String(length=128), nullable=True),
        sa.Column("compiled_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("validation_report_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("approved_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", sa.String(length=128), nullable=True),
        sa.Column("approval_reason", sa.String(length=512), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("institution_id", "version_num", name="uq_dsl_versionnum"),
    )
    op.create_index("ix_dsl_rule_set_version_institution_id", "dsl_rule_set_version", ["institution_id"])
    op.create_index("ix_dsl_rule_set_version_status", "dsl_rule_set_version", ["status"])
    op.create_index("ix_dsl_rule_set_version_effective_from", "dsl_rule_set_version", ["effective_from"])
    op.create_index("ix_dsl_rule_set_version_effective_to", "dsl_rule_set_version", ["effective_to"])
    op.create_index("ix_dsl_rule_set_version_rules_hash", "dsl_rule_set_version", ["rules_hash"])
    op.create_index("ix_dsl_rule_set_version_compiled_hash", "dsl_rule_set_version", ["compiled_hash"])

    # --- Daily evaluations & signals ---
    op.create_table(
        "daily_evaluation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institution.id"),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("run_type", run_type_enum, nullable=False),
        sa.Column("run_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_version", sa.String(length=64), server_default=sa.text("'dev'"), nullable=False),
        sa.Column(
            "profile_config_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institution_profile_config_version.id"),
            nullable=False,
        ),
        sa.Column("profile_config_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "dsl_rule_set_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("dsl_rule_set_version.id"),
            nullable=False,
        ),
        sa.Column("dsl_rules_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "profile_stats_snapshot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institution_profile_stats_snapshot.id"),
            nullable=True,
        ),
        sa.Column("profile_stats_hash", sa.String(length=128), nullable=True),
        sa.Column(
            "calendar_context_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "input_aggregate_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "computed_context_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "layer_results_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_anomaly", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("final_severity", severity_enum, server_default=sa.text("'NONE'"), nullable=False),
        sa.Column("anomaly_types", postgresql.ARRAY(sa.String(length=64)), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("institution_id", "as_of_date", "run_type", name="uq_daily_eval"),
    )
    op.create_index("ix_daily_evaluation_institution_id", "daily_evaluation", ["institution_id"])
    op.create_index("ix_daily_evaluation_as_of_date", "daily_evaluation", ["as_of_date"])
    op.create_index("ix_daily_evaluation_run_type", "daily_evaluation", ["run_type"])
    op.create_index("ix_daily_evaluation_run_at_utc", "daily_evaluation", ["run_at_utc"])
    op.create_index("ix_daily_evaluation_profile_config_hash", "daily_evaluation", ["profile_config_hash"])
    op.create_index("ix_daily_evaluation_dsl_rules_hash", "daily_evaluation", ["dsl_rules_hash"])
    op.create_index("ix_daily_evaluation_profile_stats_snapshot_id", "daily_evaluation", ["profile_stats_snapshot_id"])
    op.create_index("ix_daily_evaluation_profile_stats_hash", "daily_evaluation", ["profile_stats_hash"])
    op.create_index("ix_daily_evaluation_final_severity", "daily_evaluation", ["final_severity"])
    op.create_index("ix_daily_eval_inst_date", "daily_evaluation", ["institution_id", "as_of_date"])

    op.create_table(
        "evaluation_input_load",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_evaluation.id"),
            nullable=False,
        ),
        sa.Column("load_batch_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("load_batch.id"), nullable=False),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("evaluation_id", "load_batch_id", name="uq_eval_load"),
    )
    op.create_index("ix_eval_load_eval", "evaluation_input_load", ["evaluation_id"])
    op.create_index("ix_eval_load_batch", "evaluation_input_load", ["load_batch_id"])

    op.create_table(
        "anomaly_signal",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_evaluation.id"),
            nullable=False,
        ),
        sa.Column("layer", detection_layer_enum, nullable=False),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("metric_id", sa.String(length=64), nullable=True),
        sa.Column("occurrence_id", sa.String(length=64), nullable=True),
        sa.Column("is_triggered", sa.Boolean(), nullable=False),
        sa.Column("severity_suggested", severity_enum, nullable=False),
        sa.Column("score", sa.Numeric(24, 8), nullable=True),
        sa.Column("threshold_low", sa.Numeric(24, 8), nullable=True),
        sa.Column("threshold_high", sa.Numeric(24, 8), nullable=True),
        sa.Column(
            "explanation_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_anomaly_signal_evaluation_id", "anomaly_signal", ["evaluation_id"])
    op.create_index("ix_anomaly_signal_layer", "anomaly_signal", ["layer"])
    op.create_index("ix_anomaly_signal_signal_type", "anomaly_signal", ["signal_type"])
    op.create_index("ix_signal_eval_layer", "anomaly_signal", ["evaluation_id", "layer"])

    # --- Final anomaly (single per institution/day) ---
    op.create_table(
        "final_anomaly",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "institution_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("institution.id"),
            nullable=False,
        ),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column(
            "current_evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_evaluation.id"),
            nullable=False,
        ),
        sa.Column("version_num", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("is_anomaly", sa.Boolean(), nullable=False),
        sa.Column("severity", severity_enum, nullable=False),
        sa.Column("anomaly_types", postgresql.ARRAY(sa.String(length=64)), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("institution_id", "as_of_date", name="uq_final_anomaly"),
    )
    op.create_index("ix_final_anomaly_institution_id", "final_anomaly", ["institution_id"])
    op.create_index("ix_final_anomaly_as_of_date", "final_anomaly", ["as_of_date"])
    op.create_index("ix_final_anomaly_current_evaluation_id", "final_anomaly", ["current_evaluation_id"])
    op.create_index("ix_final_anomaly_severity", "final_anomaly", ["severity"])

    # --- LLM explanations ---
    op.create_table(
        "llm_explanation",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_evaluation.id"),
            nullable=False,
        ),
        sa.Column("status", llm_status_enum, nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("requested_at_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "prompt_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_llm_explanation_evaluation_id", "llm_explanation", ["evaluation_id"])

    # --- Audit log ---
    op.create_table(
        "audit_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("object_type", sa.String(length=128), nullable=False),
        sa.Column("object_id", sa.String(length=128), nullable=False),
        sa.Column("before_hash", sa.String(length=128), nullable=True),
        sa.Column("after_hash", sa.String(length=128), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    # --- Notifications (persisted, async delivery) ---
    op.create_table(
        "notification_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("daily_evaluation.id"),
            nullable=False,
        ),
        sa.Column(
            "final_anomaly_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("final_anomaly.id"),
            nullable=True,
        ),
        sa.Column("channel", notification_channel_enum, nullable=False),
        sa.Column("status", notification_status_enum, nullable=False),
        sa.Column("severity", severity_enum, nullable=False),
        sa.Column(
            "to_addresses",
            postgresql.ARRAY(sa.String(length=256)),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_at_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at_utc", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_notification_event_evaluation_id", "notification_event", ["evaluation_id"])
    op.create_index("ix_notification_event_final_anomaly_id", "notification_event", ["final_anomaly_id"])
    op.create_index("ix_notification_event_status", "notification_event", ["status"])
    op.create_index("ix_notification_event_severity", "notification_event", ["severity"])


def downgrade() -> None:
    op.drop_index("ix_notification_event_severity", table_name="notification_event")
    op.drop_index("ix_notification_event_status", table_name="notification_event")
    op.drop_index("ix_notification_event_final_anomaly_id", table_name="notification_event")
    op.drop_index("ix_notification_event_evaluation_id", table_name="notification_event")
    op.drop_table("notification_event")

    op.drop_table("audit_event")

    op.drop_index("ix_llm_explanation_evaluation_id", table_name="llm_explanation")
    op.drop_table("llm_explanation")

    op.drop_index("ix_final_anomaly_severity", table_name="final_anomaly")
    op.drop_index("ix_final_anomaly_current_evaluation_id", table_name="final_anomaly")
    op.drop_index("ix_final_anomaly_as_of_date", table_name="final_anomaly")
    op.drop_index("ix_final_anomaly_institution_id", table_name="final_anomaly")
    op.drop_table("final_anomaly")

    op.drop_index("ix_signal_eval_layer", table_name="anomaly_signal")
    op.drop_index("ix_anomaly_signal_signal_type", table_name="anomaly_signal")
    op.drop_index("ix_anomaly_signal_layer", table_name="anomaly_signal")
    op.drop_index("ix_anomaly_signal_evaluation_id", table_name="anomaly_signal")
    op.drop_table("anomaly_signal")

    op.drop_index("ix_eval_load_batch", table_name="evaluation_input_load")
    op.drop_index("ix_eval_load_eval", table_name="evaluation_input_load")
    op.drop_table("evaluation_input_load")

    op.drop_index("ix_daily_eval_inst_date", table_name="daily_evaluation")
    op.drop_index("ix_daily_evaluation_final_severity", table_name="daily_evaluation")
    op.drop_index("ix_daily_evaluation_profile_stats_hash", table_name="daily_evaluation")
    op.drop_index("ix_daily_evaluation_profile_stats_snapshot_id", table_name="daily_evaluation")
    op.drop_index("ix_daily_evaluation_dsl_rules_hash", table_name="daily_evaluation")
    op.drop_index("ix_daily_evaluation_profile_config_hash", table_name="daily_evaluation")
    op.drop_index("ix_daily_evaluation_run_at_utc", table_name="daily_evaluation")
    op.drop_index("ix_daily_evaluation_run_type", table_name="daily_evaluation")
    op.drop_index("ix_daily_evaluation_as_of_date", table_name="daily_evaluation")
    op.drop_index("ix_daily_evaluation_institution_id", table_name="daily_evaluation")
    op.drop_table("daily_evaluation")

    op.drop_index("ix_dsl_rule_set_version_compiled_hash", table_name="dsl_rule_set_version")
    op.drop_index("ix_dsl_rule_set_version_rules_hash", table_name="dsl_rule_set_version")
    op.drop_index("ix_dsl_rule_set_version_effective_to", table_name="dsl_rule_set_version")
    op.drop_index("ix_dsl_rule_set_version_effective_from", table_name="dsl_rule_set_version")
    op.drop_index("ix_dsl_rule_set_version_status", table_name="dsl_rule_set_version")
    op.drop_index("ix_dsl_rule_set_version_institution_id", table_name="dsl_rule_set_version")
    op.drop_table("dsl_rule_set_version")

    op.drop_index(
        "ix_institution_profile_stats_snapshot_snapshot_hash",
        table_name="institution_profile_stats_snapshot",
    )
    op.drop_index(
        "ix_institution_profile_stats_snapshot_profile_config_version_id",
        table_name="institution_profile_stats_snapshot",
    )
    op.drop_index(
        "ix_institution_profile_stats_snapshot_as_of_date",
        table_name="institution_profile_stats_snapshot",
    )
    op.drop_index(
        "ix_institution_profile_stats_snapshot_institution_id",
        table_name="institution_profile_stats_snapshot",
    )
    op.drop_table("institution_profile_stats_snapshot")

    op.drop_index(
        "ix_institution_profile_config_version_config_hash",
        table_name="institution_profile_config_version",
    )
    op.drop_index(
        "ix_institution_profile_config_version_effective_to",
        table_name="institution_profile_config_version",
    )
    op.drop_index(
        "ix_institution_profile_config_version_effective_from",
        table_name="institution_profile_config_version",
    )
    op.drop_index(
        "ix_institution_profile_config_version_status",
        table_name="institution_profile_config_version",
    )
    op.drop_index(
        "ix_institution_profile_config_version_institution_id",
        table_name="institution_profile_config_version",
    )
    op.drop_table("institution_profile_config_version")

    op.drop_index("ix_load_batch_institution_local_date", table_name="load_batch")
    op.drop_index("ix_load_batch_received_at_utc", table_name="load_batch")
    op.drop_index("ix_load_batch_institution_id", table_name="load_batch")
    op.drop_table("load_batch")

    op.drop_index("ix_institution_external_code", table_name="institution")
    op.drop_table("institution")

    op.drop_index(
        "ix_business_calendar_holiday_holiday_date",
        table_name="business_calendar_holiday",
    )
    op.drop_index(
        "ix_business_calendar_holiday_calendar_id",
        table_name="business_calendar_holiday",
    )
    op.drop_table("business_calendar_holiday")

    op.drop_index("ix_business_calendar_name", table_name="business_calendar")
    op.drop_table("business_calendar")

    # --- Enums ---
    op.execute("DROP TYPE IF EXISTS notification_channel")
    op.execute("DROP TYPE IF EXISTS notification_status")
    op.execute("DROP TYPE IF EXISTS llm_status")
    op.execute("DROP TYPE IF EXISTS detection_layer")
    op.execute("DROP TYPE IF EXISTS severity")
    op.execute("DROP TYPE IF EXISTS run_type")
    op.execute("DROP TYPE IF EXISTS version_status")
    op.execute("DROP TYPE IF EXISTS load_source")


