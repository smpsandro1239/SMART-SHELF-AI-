"""Create durable Edge observability aggregates and supervisor event storage."""

from alembic import op
import sqlalchemy as sa

revision = "0105_edge_observability_history"
down_revision = "0104_edge_task_acknowledgement_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edge_observability_aggregates",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("granularity", sa.String(length=8), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metric_name", sa.String(length=40), nullable=False),
        sa.Column("dimension_value", sa.String(length=32), nullable=False, server_default="ALL"),
        sa.Column("value_count", sa.BigInteger(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "store_id", "granularity", "window_start", "metric_name", "dimension_value",
            name="uq_edge_observability_aggregate_identity",
        ),
        sa.CheckConstraint("granularity IN ('15m', 'daily')", name="ck_edge_observability_aggregate_granularity"),
        sa.CheckConstraint("metric_name IN ('events_received')", name="ck_edge_observability_aggregate_metric"),
        sa.CheckConstraint("value_count >= 0", name="ck_edge_observability_aggregate_value"),
        sa.CheckConstraint("length(dimension_value) BETWEEN 1 AND 32", name="ck_edge_observability_aggregate_dimension"),
    )
    op.create_index(
        "ix_edge_observability_aggregate_store_window",
        "edge_observability_aggregates", ["store_id", "granularity", "window_start"],
    )
    op.create_index(
        "ix_edge_observability_aggregate_retention",
        "edge_observability_aggregates", ["window_start"],
    )

    op.create_table(
        "edge_observability_checkpoints",
        sa.Column("job_name", sa.String(length=80), primary_key=True),
        sa.Column("last_completed_window", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "edge_supervisor_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_key", sa.String(length=64), nullable=False),
        sa.Column("supervisor_instance_id", sa.String(length=120), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("worker_id", sa.String(length=160), nullable=True),
        sa.Column("reason_code", sa.String(length=48), nullable=True),
        sa.Column("restart_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_key", name="uq_edge_supervisor_event_key"),
        sa.CheckConstraint(
            "event_type IN ('STARTED', 'RESTARTING', 'FAILED', 'STOPPED', 'CHILD_EXITED', 'HEARTBEAT_STALE')",
            name="ck_edge_supervisor_event_type",
        ),
        sa.CheckConstraint("restart_count >= 0", name="ck_edge_supervisor_event_restart_count"),
        sa.CheckConstraint(
            "reason_code IS NULL OR reason_code IN "
            "('CHILD_CONFIGURATION_ERROR', 'CHILD_EXITED', 'CHILD_HEARTBEAT_STALE', "
            "'CHILD_HEARTBEAT_MISSING', 'SPAWN_FAILED', 'SHUTDOWN_REQUESTED', 'UNKNOWN')",
            name="ck_edge_supervisor_event_reason",
        ),
    )
    op.create_index(
        "ix_edge_supervisor_events_occurred_at",
        "edge_supervisor_events", ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_edge_supervisor_events_occurred_at", table_name="edge_supervisor_events")
    op.drop_table("edge_supervisor_events")
    op.drop_table("edge_observability_checkpoints")
    op.drop_index("ix_edge_observability_aggregate_retention", table_name="edge_observability_aggregates")
    op.drop_index("ix_edge_observability_aggregate_store_window", table_name="edge_observability_aggregates")
    op.drop_table("edge_observability_aggregates")
