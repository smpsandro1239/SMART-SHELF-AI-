"""Add operation identity and frozen physical provenance to inventory movements."""
from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0086_inventory_movement_identity_provenance"
down_revision = "0085_inventory_backroom_policy_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Historical rows are retained. Provenance is copied only when it is
    # explicitly present in the referenced immutable snapshot/task.
    op.add_column(
        "inventory_movements",
        sa.Column("operation_id", sa.Uuid(as_uuid=True), nullable=True),
    )
    op.add_column(
        "inventory_movements",
        sa.Column("source_location_code", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "inventory_movements",
        sa.Column("destination_shelf_id", sa.Integer(), nullable=True),
    )

    # Migration backfill is the sole controlled exception to append-only.
    # Temporarily remove only the known 0053 guards, then restore them before
    # the migration completes. The immutable evidence rows are never deleted.
    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_movements_append_only "
            "ON inventory_movements"
        )
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movements_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movements_no_delete")

    rows = bind.execute(sa.text(
        "SELECT m.id, s.location_code, t.shelf_id "
        "FROM inventory_movements AS m "
        "LEFT JOIN inventory_snapshots AS s ON s.id = m.source_snapshot_id "
        "LEFT JOIN replenishment_tasks AS t ON t.id = m.task_id"
    )).mappings().all()
    for row in rows:
        bind.execute(
            sa.text(
                "UPDATE inventory_movements "
                "SET operation_id = :operation_id, "
                "source_location_code = :source_location_code, "
                "destination_shelf_id = :destination_shelf_id "
                "WHERE id = :movement_id"
            ),
            {
                "operation_id": str(uuid4()),
                "source_location_code": row["location_code"],
                "destination_shelf_id": row["shelf_id"],
                "movement_id": row["id"],
            },
        )

    # Restore the original 0053 append-only protection unchanged.
    if dialect == "postgresql":
        op.execute("""
            CREATE TRIGGER trg_inventory_movements_append_only
            BEFORE UPDATE OR DELETE ON inventory_movements
            FOR EACH ROW
            EXECUTE FUNCTION prevent_inventory_movement_append_only_mutation_0053()
        """)
    elif dialect == "sqlite":
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

    op.create_index(
        "uq_inventory_movement_operation_id",
        "inventory_movements",
        ["operation_id"],
        unique=True,
    )

    # Existing append-only UPDATE/DELETE triggers are deliberately untouched.
    # Legacy rows may retain NULL provenance; every new row must be complete.
    if dialect == "postgresql":
        bind.exec_driver_sql("""
            CREATE FUNCTION guard_inventory_movement_provenance_0086()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                IF NEW.operation_id IS NULL
                   OR NEW.source_location_code IS NULL
                   OR length(trim(NEW.source_location_code)) = 0
                   OR NEW.destination_shelf_id IS NULL
                   OR NOT EXISTS (
                       SELECT 1
                       FROM shelves sh
                       JOIN zones z ON z.id = sh.zone_id
                       WHERE sh.id = NEW.destination_shelf_id
                         AND z.store_id = NEW.store_id
                   )
                THEN
                    RAISE EXCEPTION 'new inventory movements require operation identity and same-store physical provenance'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        bind.exec_driver_sql("""
            CREATE TRIGGER trg_inventory_movement_provenance_0086
            BEFORE INSERT ON inventory_movements
            FOR EACH ROW EXECUTE FUNCTION guard_inventory_movement_provenance_0086()
        """)
    elif dialect == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_provenance_0086
            BEFORE INSERT ON inventory_movements
            BEGIN
                SELECT CASE WHEN NEW.operation_id IS NULL
                    OR NEW.source_location_code IS NULL
                    OR length(trim(NEW.source_location_code)) = 0
                    OR NEW.destination_shelf_id IS NULL
                    OR NOT EXISTS (
                        SELECT 1 FROM shelves sh
                        JOIN zones z ON z.id = sh.zone_id
                        WHERE sh.id = NEW.destination_shelf_id
                          AND z.store_id = NEW.store_id
                    )
                    THEN RAISE(ABORT, 'new inventory movements require operation identity and same-store physical provenance')
                END;
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_movement_provenance_0086 "
            "ON inventory_movements"
        )
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_movement_provenance_0086()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_provenance_0086")

    op.drop_index("uq_inventory_movement_operation_id", table_name="inventory_movements")
    op.drop_column("inventory_movements", "destination_shelf_id")
    op.drop_column("inventory_movements", "source_location_code")
    op.drop_column("inventory_movements", "operation_id")
