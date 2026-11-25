"""Add structured task lifecycle evidence and immutable audit events."""
from alembic import op
import sqlalchemy as sa

revision = "0018_task_lifecycle_audit"
down_revision = (
    "0016_capture_sessions",
    "0016_hourly_sales_traffic",
    "0017_daily_sales_records",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("replenishment_tasks", sa.Column("actual_quantity", sa.Numeric(12, 3), nullable=True))
    op.add_column("replenishment_tasks", sa.Column("exception_reason", sa.Text(), nullable=True))
    op.create_table(
        "replenishment_task_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("replenishment_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=True),
        sa.Column("to_status", sa.String(length=16), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actual_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('APPROVED', 'STATUS_CHANGED')", name="ck_task_event_type"),
        sa.CheckConstraint("actual_quantity IS NULL OR actual_quantity > 0", name="ck_task_event_actual_quantity_positive"),
    )
    op.create_index("ix_replenishment_task_events_task_id", "replenishment_task_events", ["task_id"])
    op.create_index("ix_replenishment_task_events_actor_user_id", "replenishment_task_events", ["actor_user_id"])
    op.create_index("ix_replenishment_task_events_created_at", "replenishment_task_events", ["created_at"])
    op.create_index("ix_task_events_task_created", "replenishment_task_events", ["task_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_task_events_task_created", table_name="replenishment_task_events")
    op.drop_index("ix_replenishment_task_events_created_at", table_name="replenishment_task_events")
    op.drop_index("ix_replenishment_task_events_actor_user_id", table_name="replenishment_task_events")
    op.drop_index("ix_replenishment_task_events_task_id", table_name="replenishment_task_events")
    op.drop_table("replenishment_task_events")
    op.drop_column("replenishment_tasks", "exception_reason")
    op.drop_column("replenishment_tasks", "actual_quantity")
