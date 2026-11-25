"""Append-only audit ledger for manual inventory counts."""
from alembic import op
import sqlalchemy as sa
revision = "0091_inventory_manual_count_audit"
down_revision = "0090_shelf_product_decimal_quantities"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.create_index("uq_inventory_snapshot_identity", "inventory_snapshots", ["id", "store_id", "product_id"], unique=True)
    op.create_table("inventory_manual_count_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id", "store_id", "product_id"], ["inventory_snapshots.id", "inventory_snapshots.store_id", "inventory_snapshots.product_id"], ondelete="RESTRICT", name="fk_inventory_manual_count_snapshot_identity"),
        sa.CheckConstraint("length(trim(reason)) >= 5", name="ck_inventory_manual_count_reason_nonblank"),
        sa.UniqueConstraint("snapshot_id", name="uq_inventory_manual_count_snapshot"))
    op.create_index("ix_inventory_manual_count_store_created", "inventory_manual_count_events", ["store_id", "created_at", "id"])
    op.create_index("ix_inventory_manual_count_actor_created", "inventory_manual_count_events", ["actor_user_id", "created_at"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("""CREATE FUNCTION guard_inventory_manual_count_event_0091() RETURNS trigger LANGUAGE plpgsql AS $function$ BEGIN IF NOT EXISTS (SELECT 1 FROM inventory_snapshots s WHERE s.id=NEW.snapshot_id AND s.store_id=NEW.store_id AND s.product_id=NEW.product_id AND s.source='MANUAL') OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.actor_user_id AND (u.role='ADMIN' OR u.store_id=NEW.store_id)) THEN RAISE EXCEPTION 'manual inventory count provenance mismatch' USING ERRCODE='23514'; END IF; RETURN NEW; END; $function$""")
        bind.exec_driver_sql("CREATE TRIGGER trg_inventory_manual_count_event_provenance_0091 BEFORE INSERT ON inventory_manual_count_events FOR EACH ROW EXECUTE FUNCTION guard_inventory_manual_count_event_0091()")
        bind.exec_driver_sql("""CREATE FUNCTION prevent_inventory_manual_count_event_mutation_0091() RETURNS trigger LANGUAGE plpgsql AS $function$ BEGIN RAISE EXCEPTION 'inventory_manual_count_events is append-only' USING ERRCODE='23514'; END; $function$""")
        bind.exec_driver_sql("CREATE TRIGGER trg_inventory_manual_count_events_append_only_0091 BEFORE UPDATE OR DELETE ON inventory_manual_count_events FOR EACH ROW EXECUTE FUNCTION prevent_inventory_manual_count_event_mutation_0091()")
    elif bind.dialect.name == "sqlite":
        op.execute("""CREATE TRIGGER trg_inventory_manual_count_event_provenance_0091 BEFORE INSERT ON inventory_manual_count_events BEGIN SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM inventory_snapshots s WHERE s.id=NEW.snapshot_id AND s.store_id=NEW.store_id AND s.product_id=NEW.product_id AND s.source='MANUAL') OR NOT EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.actor_user_id AND (u.role='ADMIN' OR u.store_id=NEW.store_id)) THEN RAISE(ABORT, 'manual inventory count provenance mismatch') END; END""")
        op.execute("CREATE TRIGGER trg_inventory_manual_count_events_no_update_0091 BEFORE UPDATE ON inventory_manual_count_events BEGIN SELECT RAISE(ABORT, 'inventory_manual_count_events is append-only'); END")
        op.execute("CREATE TRIGGER trg_inventory_manual_count_events_no_delete_0091 BEFORE DELETE ON inventory_manual_count_events BEGIN SELECT RAISE(ABORT, 'inventory_manual_count_events is append-only'); END")

def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_manual_count_events_append_only_0091 ON inventory_manual_count_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_inventory_manual_count_event_mutation_0091()")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_manual_count_event_provenance_0091 ON inventory_manual_count_events")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_manual_count_event_0091()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_manual_count_events_no_update_0091")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_manual_count_events_no_delete_0091")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_manual_count_event_provenance_0091")
    op.drop_index("ix_inventory_manual_count_actor_created", table_name="inventory_manual_count_events")
    op.drop_index("ix_inventory_manual_count_store_created", table_name="inventory_manual_count_events")
    op.drop_table("inventory_manual_count_events")
    op.drop_index("uq_inventory_snapshot_identity", table_name="inventory_snapshots")
