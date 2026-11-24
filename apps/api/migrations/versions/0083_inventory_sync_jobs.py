"""Add durable, fenced ERP/WMS synchronization jobs and audit events."""
from alembic import op
import sqlalchemy as sa

revision = "0083_inventory_sync_jobs"
down_revision = "0082_inventory_external_mapping_product_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(120), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("requested_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="QUEUED"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(160), nullable=True),
        sa.Column("lease_token", sa.String(36), nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_sync_id", sa.Integer(), sa.ForeignKey("inventory_source_syncs.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('ERP', 'WMS')", name="ck_inventory_sync_job_source"),
        sa.CheckConstraint("status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')", name="ck_inventory_sync_job_status"),
        sa.CheckConstraint("attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10 AND attempt_count <= max_attempts", name="ck_inventory_sync_job_attempts"),
        sa.CheckConstraint("fencing_token >= 0", name="ck_inventory_sync_job_fencing"),
        sa.CheckConstraint("(status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'RUNNING' AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)", name="ck_inventory_sync_job_lease_state"),
        sa.CheckConstraint("(status IN ('SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED') AND finished_at IS NOT NULL) OR (status IN ('QUEUED', 'RUNNING') AND finished_at IS NULL)", name="ck_inventory_sync_job_finished_state"),
        sa.UniqueConstraint("store_id", "source", "idempotency_key", name="uq_inventory_sync_job_idempotency"),
    )
    op.create_index("ix_inventory_sync_jobs_claim", "inventory_sync_jobs", ["status", "scheduled_at", "lease_expires_at", "created_at", "id"])
    op.create_index("ix_inventory_sync_jobs_store_created", "inventory_sync_jobs", ["store_id", "created_at"])
    op.create_table(
        "inventory_sync_job_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("inventory_sync_jobs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("worker_id", sa.String(160), nullable=True),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('QUEUED', 'CLAIMED', 'LEASE_EXPIRED', 'HEARTBEAT', 'RETRY_SCHEDULED', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')", name="ck_inventory_sync_job_event_type"),
        sa.UniqueConstraint("job_id", "sequence_number", name="uq_inventory_sync_job_event_sequence"),
    )
    op.create_index("ix_inventory_sync_job_events_job_created", "inventory_sync_job_events", ["job_id", "created_at"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE FUNCTION guard_inventory_sync_job_events_0083() RETURNS trigger AS $$ BEGIN RAISE EXCEPTION 'inventory sync job events are append-only'; END; $$ LANGUAGE plpgsql")
        op.execute("CREATE TRIGGER trg_inventory_sync_job_events_0083 BEFORE UPDATE OR DELETE ON inventory_sync_job_events FOR EACH ROW EXECUTE FUNCTION guard_inventory_sync_job_events_0083()")
    elif bind.dialect.name == "sqlite":
        op.execute("CREATE TRIGGER trg_inventory_sync_job_events_update_0083 BEFORE UPDATE ON inventory_sync_job_events BEGIN SELECT RAISE(ABORT, 'inventory sync job events are append-only'); END")
        op.execute("CREATE TRIGGER trg_inventory_sync_job_events_delete_0083 BEFORE DELETE ON inventory_sync_job_events BEGIN SELECT RAISE(ABORT, 'inventory sync job events are append-only'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_sync_job_events_0083 ON inventory_sync_job_events")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_sync_job_events_0083()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_sync_job_events_update_0083")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_sync_job_events_delete_0083")
    op.drop_index("ix_inventory_sync_job_events_job_created", table_name="inventory_sync_job_events")
    op.drop_table("inventory_sync_job_events")
    op.drop_index("ix_inventory_sync_jobs_store_created", table_name="inventory_sync_jobs")
    op.drop_index("ix_inventory_sync_jobs_claim", table_name="inventory_sync_jobs")
    op.drop_table("inventory_sync_jobs")
