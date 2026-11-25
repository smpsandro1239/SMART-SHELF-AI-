"""Create an append-only lifecycle ledger for inventory movements."""
from alembic import op
import sqlalchemy as sa

revision = "0087_inventory_movement_event_ledger"
down_revision = "0086_inventory_movement_identity_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_movement_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("movement_id", sa.Integer(), sa.ForeignKey("inventory_movements.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("operation_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('MOVEMENT_RECORDED', 'WMS_CONFIRMATION_RECORDED', 'COMPENSATION_RECORDED', 'DISCREPANCY_RECORDED')", name="ck_inventory_movement_event_type"),
        sa.UniqueConstraint("movement_id", "event_type", name="uq_inventory_movement_event_type"),
    )
    op.create_index("ix_inventory_movement_events_store_created", "inventory_movement_events", ["store_id", "created_at", "id"])
    op.create_index("ix_inventory_movement_events_operation", "inventory_movement_events", ["operation_id"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql("""
            CREATE FUNCTION guard_inventory_movement_event_0087()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM inventory_movements movement
                    WHERE movement.id = NEW.movement_id
                      AND movement.operation_id = NEW.operation_id
                      AND movement.store_id = NEW.store_id
                      AND movement.actor_user_id = NEW.actor_user_id
                      AND movement.reason = NEW.reason
                ) THEN
                    RAISE EXCEPTION 'inventory movement event provenance mismatch' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        bind.exec_driver_sql("""
            CREATE TRIGGER trg_inventory_movement_event_provenance_0087
            BEFORE INSERT ON inventory_movement_events
            FOR EACH ROW EXECUTE FUNCTION guard_inventory_movement_event_0087()
        """)
        bind.exec_driver_sql("""
            CREATE FUNCTION prevent_inventory_movement_event_mutation_0087()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'inventory_movement_events is append-only' USING ERRCODE = '23514';
            END;
            $function$
        """)
        bind.exec_driver_sql("""
            CREATE TRIGGER trg_inventory_movement_events_append_only_0087
            BEFORE UPDATE OR DELETE ON inventory_movement_events
            FOR EACH ROW EXECUTE FUNCTION prevent_inventory_movement_event_mutation_0087()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_event_provenance_0087
            BEFORE INSERT ON inventory_movement_events
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM inventory_movements movement
                    WHERE movement.id = NEW.movement_id
                      AND movement.operation_id = NEW.operation_id
                      AND movement.store_id = NEW.store_id
                      AND movement.actor_user_id = NEW.actor_user_id
                      AND movement.reason = NEW.reason
                )
                THEN RAISE(ABORT, 'inventory movement event provenance mismatch')
                END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_events_no_update_0087
            BEFORE UPDATE ON inventory_movement_events
            BEGIN SELECT RAISE(ABORT, 'inventory_movement_events is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_events_no_delete_0087
            BEFORE DELETE ON inventory_movement_events
            BEGIN SELECT RAISE(ABORT, 'inventory_movement_events is append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_events_append_only_0087 ON inventory_movement_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_inventory_movement_event_mutation_0087()")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_event_provenance_0087 ON inventory_movement_events")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_movement_event_0087()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_events_no_update_0087")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_events_no_delete_0087")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_event_provenance_0087")
    op.drop_index("ix_inventory_movement_events_operation", table_name="inventory_movement_events")
    op.drop_index("ix_inventory_movement_events_store_created", table_name="inventory_movement_events")
    op.drop_table("inventory_movement_events")
