"""Require an explicitly AVAILABLE WMS snapshot for new inventory movements."""

from alembic import op

revision = "0088_inventory_movement_available_source_guard"
down_revision = "0087_inventory_movement_event_ledger"
branch_labels = None
depends_on = None


def _install_guard(*, require_available: bool) -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    availability_clause = (
        "AND source.availability_status = 'AVAILABLE'"
        if require_available
        else ""
    )

    if dialect == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_movement_provenance_0086 "
            "ON inventory_movements"
        )
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_movement_provenance_0086()")
        bind.exec_driver_sql(f"""
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
                       FROM replenishment_tasks task
                       JOIN shelves sh ON sh.id = task.shelf_id
                       JOIN zones z ON z.id = sh.zone_id
                       JOIN inventory_snapshots source ON source.id = NEW.source_snapshot_id
                       WHERE task.id = NEW.task_id
                         AND task.shelf_id = NEW.destination_shelf_id
                         AND task.store_id = NEW.store_id
                         AND task.product_id = NEW.product_id
                         AND z.store_id = NEW.store_id
                         AND source.store_id = NEW.store_id
                         AND source.product_id = NEW.product_id
                         AND source.source = 'WMS'
                         AND source.location_code = NEW.source_location_code
                         {availability_clause}
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
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_provenance_0086")
        op.execute(f"""
            CREATE TRIGGER trg_inventory_movement_provenance_0086
            BEFORE INSERT ON inventory_movements
            WHEN NOT EXISTS (
                SELECT 1
                FROM replenishment_tasks task
                JOIN shelves sh ON sh.id = task.shelf_id
                JOIN zones z ON z.id = sh.zone_id
                JOIN inventory_snapshots source ON source.id = NEW.source_snapshot_id
                WHERE task.id = NEW.task_id
                  AND task.shelf_id = NEW.destination_shelf_id
                  AND task.store_id = NEW.store_id
                  AND task.product_id = NEW.product_id
                  AND z.store_id = NEW.store_id
                  AND source.store_id = NEW.store_id
                  AND source.product_id = NEW.product_id
                  AND source.source = 'WMS'
                  AND source.location_code = NEW.source_location_code
                  {availability_clause}
            )
            BEGIN
                SELECT RAISE(ABORT, 'new inventory movements require operation identity and same-store physical provenance');
            END
        """)


def upgrade() -> None:
    _install_guard(require_available=True)


def downgrade() -> None:
    _install_guard(require_available=False)
