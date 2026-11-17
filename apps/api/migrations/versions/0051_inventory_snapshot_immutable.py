"""Protect operational inventory snapshots as append-only evidence."""

from alembic import op


revision = "0051_inventory_snapshot_immutable"
down_revision = "0050_shelf_record_store_lineage_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_inventory_snapshot_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'inventory_snapshots is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_snapshots_append_only
            BEFORE UPDATE OR DELETE ON inventory_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION prevent_inventory_snapshot_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_snapshots_no_update
            BEFORE UPDATE ON inventory_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'inventory_snapshots is append-only');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_snapshots_no_delete
            BEFORE DELETE ON inventory_snapshots
            BEGIN
                SELECT RAISE(ABORT, 'inventory_snapshots is append-only');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_snapshots_append_only "
            "ON inventory_snapshots"
        )
        op.execute("DROP FUNCTION IF EXISTS prevent_inventory_snapshot_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_snapshots_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_snapshots_no_delete")
