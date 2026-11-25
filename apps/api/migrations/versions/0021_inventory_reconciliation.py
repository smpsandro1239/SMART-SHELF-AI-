"""Add approved immutable inventory reconciliation movements."""
from alembic import op
import sqlalchemy as sa

revision = "0021_inventory_reconciliation"
down_revision = "0020_active_task_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("replenishment_tasks.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("movement_type", sa.String(length=30), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("source_snapshot_id", sa.Integer(), sa.ForeignKey("inventory_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("result_snapshot_id", sa.Integer(), sa.ForeignKey("inventory_snapshots.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_inventory_movement_task"),
        sa.UniqueConstraint("result_snapshot_id", name="uq_inventory_movement_result_snapshot"),
        sa.CheckConstraint("movement_type = 'BACKROOM_TO_SHELF'", name="ck_inventory_movement_type"),
        sa.CheckConstraint("quantity > 0", name="ck_inventory_movement_quantity_positive"),
        sa.CheckConstraint("source_snapshot_id <> result_snapshot_id", name="ck_inventory_movement_distinct_snapshots"),
    )
    op.create_index("ix_inventory_movements_store_id", "inventory_movements", ["store_id"])
    op.create_index("ix_inventory_movements_product_id", "inventory_movements", ["product_id"])
    op.create_index("ix_inventory_movements_source_snapshot_id", "inventory_movements", ["source_snapshot_id"])
    op.create_index("ix_inventory_movements_actor_user_id", "inventory_movements", ["actor_user_id"])
    op.create_index("ix_inventory_movements_created_at", "inventory_movements", ["created_at"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_inventory_movement_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                RAISE EXCEPTION 'inventory_movements is append-only';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movements_append_only
            BEFORE UPDATE OR DELETE ON inventory_movements
            FOR EACH ROW EXECUTE FUNCTION prevent_inventory_movement_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_movements_no_update
            BEFORE UPDATE ON inventory_movements
            BEGIN SELECT RAISE(ABORT, 'inventory_movements is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movements_no_delete
            BEFORE DELETE ON inventory_movements
            BEGIN SELECT RAISE(ABORT, 'inventory_movements is append-only'); END
        """)

    with op.batch_alter_table("replenishment_task_events") as batch:
        batch.drop_constraint("ck_task_event_type", type_="check")
        batch.create_check_constraint(
            "ck_task_event_type",
            "event_type IN ('CREATED', 'APPROVED', 'STATUS_CHANGED', 'INVENTORY_RECONCILED')",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movements_append_only ON inventory_movements")
        op.execute("DROP FUNCTION IF EXISTS prevent_inventory_movement_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movements_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movements_no_delete")

    with op.batch_alter_table("replenishment_task_events") as batch:
        batch.drop_constraint("ck_task_event_type", type_="check")
        batch.create_check_constraint(
            "ck_task_event_type",
            "event_type IN ('CREATED', 'APPROVED', 'STATUS_CHANGED')",
        )
    op.drop_index("ix_inventory_movements_created_at", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_actor_user_id", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_source_snapshot_id", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_product_id", table_name="inventory_movements")
    op.drop_index("ix_inventory_movements_store_id", table_name="inventory_movements")
    op.drop_table("inventory_movements")
