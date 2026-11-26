"""Freeze the physical destination shelf code on every inventory movement."""
from alembic import op
import sqlalchemy as sa

revision = "0094_inventory_movement_destination_snapshot"
down_revision = "0093_inventory_temporal_skew_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inventory_movements", sa.Column("destination_shelf_code", sa.String(length=80), nullable=True))
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            UPDATE inventory_movements AS movement
            SET destination_shelf_id = task.shelf_id
            FROM replenishment_tasks AS task
            WHERE task.id = movement.task_id
              AND movement.destination_shelf_id IS NULL
        """)
        op.execute("""
            UPDATE inventory_movements AS movement
            SET destination_shelf_code = shelf.code
            FROM replenishment_tasks AS task
            JOIN shelves AS shelf ON shelf.id = task.shelf_id
            WHERE task.id = movement.task_id
              AND task.shelf_id = movement.destination_shelf_id
        """)
        invalid = bind.execute(sa.text("""
            SELECT COUNT(*) FROM inventory_movements AS movement
            LEFT JOIN replenishment_tasks AS task ON task.id = movement.task_id
            LEFT JOIN shelves AS shelf ON shelf.id = task.shelf_id
            LEFT JOIN zones AS zone ON zone.id = shelf.zone_id
            WHERE movement.destination_shelf_id IS NULL
               OR movement.destination_shelf_code IS NULL
               OR movement.destination_shelf_id <> task.shelf_id
               OR movement.destination_shelf_code <> shelf.code
               OR movement.store_id <> task.store_id
               OR movement.store_id <> zone.store_id
        """)).scalar_one()
        if invalid:
            raise RuntimeError(f"Cannot backfill {invalid} inventory movements with a valid destination shelf")
        op.alter_column("inventory_movements", "destination_shelf_code", nullable=False)
        op.create_check_constraint(
            "ck_inventory_movement_destination_snapshot_required",
            "inventory_movements",
            "destination_shelf_id IS NOT NULL AND destination_shelf_code IS NOT NULL "
            "AND length(trim(destination_shelf_code)) BETWEEN 1 AND 80",
        )
        op.execute("""
            CREATE FUNCTION enforce_inventory_movement_destination_snapshot_0094()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM replenishment_tasks AS task
                    JOIN shelves AS shelf ON shelf.id = task.shelf_id
                    JOIN zones AS zone ON zone.id = shelf.zone_id
                    WHERE task.id = NEW.task_id
                      AND task.store_id = NEW.store_id
                      AND task.shelf_id = NEW.destination_shelf_id
                      AND shelf.code = NEW.destination_shelf_code
                      AND zone.store_id = NEW.store_id
                ) THEN
                    RAISE EXCEPTION 'inventory movement destination shelf provenance mismatch'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_destination_snapshot_0094
            BEFORE INSERT ON inventory_movements
            FOR EACH ROW EXECUTE FUNCTION enforce_inventory_movement_destination_snapshot_0094()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            UPDATE inventory_movements
            SET destination_shelf_id = (
                SELECT task.shelf_id FROM replenishment_tasks AS task
                WHERE task.id = inventory_movements.task_id
            )
            WHERE destination_shelf_id IS NULL
        """)
        op.execute("""
            UPDATE inventory_movements
            SET destination_shelf_code = (
                SELECT shelf.code
                FROM replenishment_tasks AS task
                JOIN shelves AS shelf ON shelf.id = task.shelf_id
                JOIN zones AS zone ON zone.id = shelf.zone_id
                WHERE task.id = inventory_movements.task_id
                  AND task.shelf_id = inventory_movements.destination_shelf_id
                  AND task.store_id = inventory_movements.store_id
                  AND zone.store_id = inventory_movements.store_id
            )
        """)
        invalid = bind.execute(sa.text("""
            SELECT COUNT(*) FROM inventory_movements AS movement
            LEFT JOIN replenishment_tasks AS task ON task.id = movement.task_id
            LEFT JOIN shelves AS shelf ON shelf.id = task.shelf_id
            LEFT JOIN zones AS zone ON zone.id = shelf.zone_id
            WHERE movement.destination_shelf_id IS NULL
               OR movement.destination_shelf_code IS NULL
               OR movement.destination_shelf_id <> task.shelf_id
               OR movement.destination_shelf_code <> shelf.code
               OR movement.store_id <> task.store_id
               OR movement.store_id <> zone.store_id
        """)).scalar_one()
        if invalid:
            raise RuntimeError(f"Cannot backfill {invalid} inventory movements with a valid destination shelf")
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_destination_snapshot_0094
            BEFORE INSERT ON inventory_movements
            WHEN NEW.destination_shelf_id IS NULL
              OR NEW.destination_shelf_code IS NULL
              OR length(trim(NEW.destination_shelf_code)) NOT BETWEEN 1 AND 80
              OR NOT EXISTS (
                    SELECT 1
                    FROM replenishment_tasks AS task
                    JOIN shelves AS shelf ON shelf.id = task.shelf_id
                    JOIN zones AS zone ON zone.id = shelf.zone_id
                    WHERE task.id = NEW.task_id
                      AND task.store_id = NEW.store_id
                      AND task.shelf_id = NEW.destination_shelf_id
                      AND shelf.code = NEW.destination_shelf_code
                      AND zone.store_id = NEW.store_id
              )
            BEGIN
                SELECT RAISE(ABORT, 'inventory movement destination shelf provenance mismatch');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_destination_snapshot_0094 ON inventory_movements")
        op.execute("DROP FUNCTION IF EXISTS enforce_inventory_movement_destination_snapshot_0094()")
        op.drop_constraint("ck_inventory_movement_destination_snapshot_required", "inventory_movements", type_="check")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_destination_snapshot_0094")
    op.drop_column("inventory_movements", "destination_shelf_code")
