"""Add durable processing state and fenced leases for Edge device events."""

from alembic import op
import sqlalchemy as sa


revision = "0073_edge_event_processing"
down_revision = "0072_edge_device_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "edge_device_event_processing",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "inbox_id", sa.Integer(),
            sa.ForeignKey("edge_device_event_inbox.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_owner", sa.String(length=160), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("inbox_id", name="uq_edge_event_processing_inbox"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'PROCESSED', 'RETRY', 'DEAD_LETTER')",
            name="ck_edge_event_processing_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts > 0",
            name="ck_edge_event_processing_attempts",
        ),
        sa.CheckConstraint("fencing_token >= 0", name="ck_edge_event_processing_fencing"),
        sa.CheckConstraint(
            "(status = 'PROCESSING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'PROCESSING' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_edge_event_processing_lease_state",
        ),
        sa.CheckConstraint(
            "(status IN ('PROCESSED', 'DEAD_LETTER') AND finished_at IS NOT NULL) "
            "OR (status NOT IN ('PROCESSED', 'DEAD_LETTER') AND finished_at IS NULL)",
            name="ck_edge_event_processing_finished_state",
        ),
    )
    op.create_index(
        "ix_edge_event_processing_claim",
        "edge_device_event_processing",
        ["status", "available_at", "lease_expires_at", "id"],
    )
    op.create_index(
        "ix_edge_event_processing_status_updated",
        "edge_device_event_processing",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_edge_event_processing_status_updated", table_name="edge_device_event_processing")
    op.drop_index("ix_edge_event_processing_claim", table_name="edge_device_event_processing")
    op.drop_table("edge_device_event_processing")
