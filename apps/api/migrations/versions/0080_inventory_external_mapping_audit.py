"""Add append-only audit events for external inventory product mappings."""
from alembic import op
import sqlalchemy as sa

revision = "0080_inventory_external_mapping_audit"
down_revision = "0079_inventory_sync_run_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_external_product_mapping_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mapping_id", sa.Integer(), sa.ForeignKey("inventory_external_product_mappings.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(12), nullable=False),
        sa.Column("before_state", sa.JSON(), nullable=True),
        sa.Column("after_state", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('CREATED', 'UPDATED', 'DEACTIVATED', 'REACTIVATED')", name="ck_inventory_external_mapping_event_type"),
    )
    op.create_index(
        "ix_inventory_external_mapping_events_mapping_created",
        "inventory_external_product_mapping_events",
        ["mapping_id", "created_at"],
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
        CREATE FUNCTION guard_inventory_external_mapping_events_0080() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'inventory external product mapping events are append-only'; END;
        $$ LANGUAGE plpgsql
        """)
        op.execute("CREATE TRIGGER trg_inventory_external_mapping_events_0080 BEFORE UPDATE OR DELETE ON inventory_external_product_mapping_events FOR EACH ROW EXECUTE FUNCTION guard_inventory_external_mapping_events_0080()")
    elif bind.dialect.name == "sqlite":
        op.execute("CREATE TRIGGER trg_inventory_external_mapping_events_update_0080 BEFORE UPDATE ON inventory_external_product_mapping_events BEGIN SELECT RAISE(ABORT, 'inventory external product mapping events are append-only'); END")
        op.execute("CREATE TRIGGER trg_inventory_external_mapping_events_delete_0080 BEFORE DELETE ON inventory_external_product_mapping_events BEGIN SELECT RAISE(ABORT, 'inventory external product mapping events are append-only'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_external_mapping_events_0080 ON inventory_external_product_mapping_events")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_external_mapping_events_0080()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_external_mapping_events_update_0080")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_external_mapping_events_delete_0080")
    op.drop_index("ix_inventory_external_mapping_events_mapping_created", table_name="inventory_external_product_mapping_events")
    op.drop_table("inventory_external_product_mapping_events")
