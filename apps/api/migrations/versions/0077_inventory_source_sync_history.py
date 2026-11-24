"""Persist ERP/WMS synchronization attempts and append-only audit events."""
from alembic import op
import sqlalchemy as sa

revision = "0077_inventory_source_sync_history"
down_revision = "0076_inventory_reconciliation_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_source_syncs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("provider", sa.String(120), nullable=False),
        sa.Column("external_run_id", sa.String(200), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="STARTED"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_records", sa.Integer(), nullable=True),
        sa.Column("processed_records", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source IN ('ERP', 'WMS')", name="ck_inventory_source_sync_source"),
        sa.CheckConstraint("status IN ('STARTED', 'SUCCESS', 'PARTIAL', 'FAILED')", name="ck_inventory_source_sync_status"),
        sa.CheckConstraint("received_records IS NULL OR received_records >= 0", name="ck_inventory_source_sync_received_nonnegative"),
        sa.CheckConstraint("processed_records IS NULL OR processed_records >= 0", name="ck_inventory_source_sync_processed_nonnegative"),
        sa.CheckConstraint("processed_records IS NULL OR received_records IS NULL OR processed_records <= received_records", name="ck_inventory_source_sync_processed_lte_received"),
        sa.CheckConstraint("(status = 'STARTED' AND finished_at IS NULL) OR (status <> 'STARTED' AND finished_at IS NOT NULL)", name="ck_inventory_source_sync_completion_time"),
    )
    op.create_index("ix_inventory_source_sync_store_source_started", "inventory_source_syncs", ["store_id", "source", "started_at"])
    op.create_index("ix_inventory_source_sync_store_status_started", "inventory_source_syncs", ["store_id", "status", "started_at"])
    op.create_table(
        "inventory_source_sync_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sync_id", sa.Integer(), sa.ForeignKey("inventory_source_syncs.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(12), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('STARTED', 'COMPLETED')", name="ck_inventory_source_sync_event_type"),
    )
    op.create_index("ix_inventory_source_sync_events_sync_created", "inventory_source_sync_events", ["sync_id", "created_at"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
        CREATE FUNCTION guard_inventory_source_sync_lifecycle_0077() RETURNS trigger AS $$
        BEGIN
            IF OLD.status <> 'STARTED' OR NEW.status NOT IN ('SUCCESS', 'PARTIAL', 'FAILED')
               OR NEW.store_id IS DISTINCT FROM OLD.store_id OR NEW.source IS DISTINCT FROM OLD.source
               OR NEW.provider IS DISTINCT FROM OLD.provider OR NEW.external_run_id IS DISTINCT FROM OLD.external_run_id
               OR NEW.started_at IS DISTINCT FROM OLD.started_at OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
               OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.finished_at IS NULL THEN
                RAISE EXCEPTION 'inventory source sync lifecycle permits one STARTED-to-terminal transition only';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("CREATE TRIGGER trg_inventory_source_sync_lifecycle_0077 BEFORE UPDATE ON inventory_source_syncs FOR EACH ROW EXECUTE FUNCTION guard_inventory_source_sync_lifecycle_0077()")
        op.execute("""
        CREATE FUNCTION guard_inventory_source_sync_event_append_only_0077() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'inventory source sync events are append-only'; END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("CREATE TRIGGER trg_inventory_source_sync_event_append_only_0077 BEFORE UPDATE OR DELETE ON inventory_source_sync_events FOR EACH ROW EXECUTE FUNCTION guard_inventory_source_sync_event_append_only_0077()")
        op.execute("""
        CREATE FUNCTION guard_inventory_source_sync_delete_0077() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'inventory source sync history cannot be deleted'; END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("CREATE TRIGGER trg_inventory_source_sync_delete_0077 BEFORE DELETE ON inventory_source_syncs FOR EACH ROW EXECUTE FUNCTION guard_inventory_source_sync_delete_0077()")
    elif bind.dialect.name == "sqlite":
        op.execute("""
        CREATE TRIGGER trg_inventory_source_sync_lifecycle_0077 BEFORE UPDATE ON inventory_source_syncs
        WHEN OLD.status <> 'STARTED' OR NEW.status NOT IN ('SUCCESS', 'PARTIAL', 'FAILED')
          OR NEW.store_id IS NOT OLD.store_id OR NEW.source IS NOT OLD.source
          OR NEW.provider IS NOT OLD.provider OR NEW.external_run_id IS NOT OLD.external_run_id
          OR NEW.started_at IS NOT OLD.started_at OR NEW.created_by_user_id IS NOT OLD.created_by_user_id
          OR NEW.created_at IS NOT OLD.created_at OR NEW.finished_at IS NULL
        BEGIN SELECT RAISE(ABORT, 'inventory source sync lifecycle permits one STARTED-to-terminal transition only'); END
        """)
        op.execute("CREATE TRIGGER trg_inventory_source_sync_event_update_0077 BEFORE UPDATE ON inventory_source_sync_events BEGIN SELECT RAISE(ABORT, 'inventory source sync events are append-only'); END")
        op.execute("CREATE TRIGGER trg_inventory_source_sync_event_delete_0077 BEFORE DELETE ON inventory_source_sync_events BEGIN SELECT RAISE(ABORT, 'inventory source sync events are append-only'); END")
        op.execute("CREATE TRIGGER trg_inventory_source_sync_delete_0077 BEFORE DELETE ON inventory_source_syncs BEGIN SELECT RAISE(ABORT, 'inventory source sync history cannot be deleted'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_source_sync_lifecycle_0077 ON inventory_source_syncs")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_source_sync_lifecycle_0077()")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_source_sync_event_append_only_0077 ON inventory_source_sync_events")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_source_sync_event_append_only_0077()")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_source_sync_delete_0077 ON inventory_source_syncs")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_source_sync_delete_0077()")
    elif bind.dialect.name == "sqlite":
        for name in ("trg_inventory_source_sync_lifecycle_0077", "trg_inventory_source_sync_event_update_0077", "trg_inventory_source_sync_event_delete_0077", "trg_inventory_source_sync_delete_0077"):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_inventory_source_sync_events_sync_created", table_name="inventory_source_sync_events")
    op.drop_table("inventory_source_sync_events")
    op.drop_index("ix_inventory_source_sync_store_status_started", table_name="inventory_source_syncs")
    op.drop_index("ix_inventory_source_sync_store_source_started", table_name="inventory_source_syncs")
    op.drop_table("inventory_source_syncs")
