"""Make approved inventory movements append-only at the database boundary."""

from alembic import op


revision = "0053_inventory_movement_append_only"
down_revision = "0052_inventory_movement_lineage_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_inventory_movement_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                RAISE EXCEPTION 'inventory_movements is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movements_append_only
            BEFORE UPDATE OR DELETE ON inventory_movements
            FOR EACH ROW
            EXECUTE FUNCTION prevent_inventory_movement_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_movements_no_update
            BEFORE UPDATE ON inventory_movements
            BEGIN
                SELECT RAISE(ABORT, 'inventory_movements is append-only');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movements_no_delete
            BEFORE DELETE ON inventory_movements
            BEGIN
                SELECT RAISE(ABORT, 'inventory_movements is append-only');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_movements_append_only "
            "ON inventory_movements"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_inventory_movement_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movements_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movements_no_delete")
