"""Freeze destination zone identity and mark historical hierarchy backfills."""
from alembic import op
import sqlalchemy as sa

revision = "0095_inventory_movement_destination_zone"
down_revision = "0094_inventory_movement_destination_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inventory_movements", sa.Column("destination_zone_id", sa.Integer(), nullable=True))
    op.add_column("inventory_movements", sa.Column("destination_zone_name", sa.String(length=120), nullable=True))
    op.add_column("inventory_movements", sa.Column("destination_location_backfilled", sa.Boolean(), nullable=False, server_default=sa.false()))
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            UPDATE inventory_movements AS movement
            SET destination_zone_id = zone.id,
                destination_zone_name = zone.name,
                destination_location_backfilled = TRUE
            FROM replenishment_tasks AS task
            JOIN shelves AS shelf ON shelf.id = task.shelf_id
            JOIN zones AS zone ON zone.id = shelf.zone_id
            WHERE task.id = movement.task_id
              AND task.shelf_id = movement.destination_shelf_id
              AND task.store_id = movement.store_id
              AND shelf.code = movement.destination_shelf_code
              AND zone.store_id = movement.store_id
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            UPDATE inventory_movements
            SET destination_zone_id = (
                    SELECT zone.id
                    FROM replenishment_tasks AS task
                    JOIN shelves AS shelf ON shelf.id = task.shelf_id
                    JOIN zones AS zone ON zone.id = shelf.zone_id
                    WHERE task.id = inventory_movements.task_id
                      AND task.shelf_id = inventory_movements.destination_shelf_id
                      AND task.store_id = inventory_movements.store_id
                      AND shelf.code = inventory_movements.destination_shelf_code
                      AND zone.store_id = inventory_movements.store_id
                ),
                destination_zone_name = (
                    SELECT zone.name
                    FROM replenishment_tasks AS task
                    JOIN shelves AS shelf ON shelf.id = task.shelf_id
                    JOIN zones AS zone ON zone.id = shelf.zone_id
                    WHERE task.id = inventory_movements.task_id
                      AND task.shelf_id = inventory_movements.destination_shelf_id
                      AND task.store_id = inventory_movements.store_id
                      AND shelf.code = inventory_movements.destination_shelf_code
                      AND zone.store_id = inventory_movements.store_id
                ),
                destination_location_backfilled = TRUE
        """)
    invalid = bind.execute(sa.text("""
        SELECT COUNT(*) FROM inventory_movements AS movement
        LEFT JOIN replenishment_tasks AS task ON task.id = movement.task_id
        LEFT JOIN shelves AS shelf ON shelf.id = task.shelf_id
        LEFT JOIN zones AS zone ON zone.id = shelf.zone_id
        WHERE movement.destination_zone_id IS NULL
           OR movement.destination_zone_name IS NULL
           OR length(trim(movement.destination_zone_name)) NOT BETWEEN 1 AND 120
           OR movement.destination_zone_id <> zone.id
           OR movement.destination_zone_name <> zone.name
           OR task.shelf_id <> movement.destination_shelf_id
           OR shelf.code <> movement.destination_shelf_code
           OR task.store_id <> movement.store_id
           OR zone.store_id <> movement.store_id
           OR movement.destination_location_backfilled IS NOT TRUE
    """)).scalar_one()
    if invalid:
        raise RuntimeError(f"Cannot backfill {invalid} inventory movements with a valid destination zone")

    if bind.dialect.name == "postgresql":
        op.alter_column("inventory_movements", "destination_zone_id", nullable=False)
        op.alter_column("inventory_movements", "destination_zone_name", nullable=False)
        op.create_check_constraint(
            "ck_inventory_movement_destination_zone_snapshot_required",
            "inventory_movements",
            "destination_zone_id IS NOT NULL AND destination_zone_name IS NOT NULL "
            "AND length(trim(destination_zone_name)) BETWEEN 1 AND 120",
        )
        op.execute("""
            CREATE FUNCTION enforce_inventory_movement_destination_zone_0095()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NEW.destination_location_backfilled IS TRUE OR NOT EXISTS (
                    SELECT 1
                    FROM replenishment_tasks AS task
                    JOIN shelves AS shelf ON shelf.id = task.shelf_id
                    JOIN zones AS zone ON zone.id = shelf.zone_id
                    WHERE task.id = NEW.task_id
                      AND task.store_id = NEW.store_id
                      AND task.shelf_id = NEW.destination_shelf_id
                      AND shelf.code = NEW.destination_shelf_code
                      AND zone.id = NEW.destination_zone_id
                      AND zone.name = NEW.destination_zone_name
                      AND zone.store_id = NEW.store_id
                ) THEN
                    RAISE EXCEPTION 'inventory movement destination zone provenance mismatch'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_destination_zone_0095
            BEFORE INSERT ON inventory_movements
            FOR EACH ROW EXECUTE FUNCTION enforce_inventory_movement_destination_zone_0095()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_destination_zone_0095
            BEFORE INSERT ON inventory_movements
            WHEN NEW.destination_zone_id IS NULL
              OR NEW.destination_zone_name IS NULL
              OR length(trim(NEW.destination_zone_name)) NOT BETWEEN 1 AND 120
              OR NEW.destination_location_backfilled <> 0
              OR NOT EXISTS (
                    SELECT 1
                    FROM replenishment_tasks AS task
                    JOIN shelves AS shelf ON shelf.id = task.shelf_id
                    JOIN zones AS zone ON zone.id = shelf.zone_id
                    WHERE task.id = NEW.task_id
                      AND task.store_id = NEW.store_id
                      AND task.shelf_id = NEW.destination_shelf_id
                      AND shelf.code = NEW.destination_shelf_code
                      AND zone.id = NEW.destination_zone_id
                      AND zone.name = NEW.destination_zone_name
                      AND zone.store_id = NEW.store_id
              )
            BEGIN
                SELECT RAISE(ABORT, 'inventory movement destination zone provenance mismatch');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_destination_zone_0095 ON inventory_movements")
        op.execute("DROP FUNCTION IF EXISTS enforce_inventory_movement_destination_zone_0095()")
        op.drop_constraint("ck_inventory_movement_destination_zone_snapshot_required", "inventory_movements", type_="check")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_destination_zone_0095")
    op.drop_column("inventory_movements", "destination_location_backfilled")
    op.drop_column("inventory_movements", "destination_zone_name")
    op.drop_column("inventory_movements", "destination_zone_id")
