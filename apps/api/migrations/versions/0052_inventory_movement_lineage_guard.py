"""Enforce same-store/product lineage and quantity conservation for stock movements."""

from alembic import op


revision = "0052_inventory_movement_lineage_guard"
down_revision = "0051_inventory_snapshot_immutable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION enforce_inventory_movement_lineage()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM replenishment_tasks AS task
                    JOIN inventory_snapshots AS source
                      ON source.id = NEW.source_snapshot_id
                    JOIN inventory_snapshots AS result
                      ON result.id = NEW.result_snapshot_id
                    WHERE task.id = NEW.task_id
                      AND task.status = 'COMPLETED'
                      AND task.completed_at IS NOT NULL
                      AND task.actual_quantity = NEW.quantity
                      AND task.store_id = NEW.store_id
                      AND task.product_id = NEW.product_id
                      AND source.store_id = NEW.store_id
                      AND source.product_id = NEW.product_id
                      AND result.store_id = NEW.store_id
                      AND result.product_id = NEW.product_id
                      AND source.captured_at <= task.completed_at
                      AND result.captured_at >= task.completed_at
                      AND result.source = 'MANUAL'
                      AND result.external_reference =
                          'TASK-RECONCILIATION-' || task.id::text
                      AND result.reserved_quantity = source.reserved_quantity
                      AND result.on_hand_quantity = source.on_hand_quantity
                          - COALESCE((
                              SELECT SUM(previous.quantity)
                              FROM inventory_movements AS previous
                              WHERE previous.source_snapshot_id = source.id
                          ), 0)
                          - NEW.quantity
                ) THEN
                    RAISE EXCEPTION 'inventory movement lineage or quantity conservation is invalid'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_lineage_guard
            BEFORE INSERT ON inventory_movements
            FOR EACH ROW
            EXECUTE FUNCTION enforce_inventory_movement_lineage()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_lineage_guard
            BEFORE INSERT ON inventory_movements
            WHEN NOT EXISTS (
                SELECT 1
                FROM replenishment_tasks AS task
                JOIN inventory_snapshots AS source
                  ON source.id = NEW.source_snapshot_id
                JOIN inventory_snapshots AS result
                  ON result.id = NEW.result_snapshot_id
                WHERE task.id = NEW.task_id
                  AND task.status = 'COMPLETED'
                  AND task.completed_at IS NOT NULL
                  AND task.actual_quantity = NEW.quantity
                  AND task.store_id = NEW.store_id
                  AND task.product_id = NEW.product_id
                  AND source.store_id = NEW.store_id
                  AND source.product_id = NEW.product_id
                  AND result.store_id = NEW.store_id
                  AND result.product_id = NEW.product_id
                  AND source.captured_at <= task.completed_at
                  AND result.captured_at >= task.completed_at
                  AND result.source = 'MANUAL'
                  AND result.external_reference =
                      'TASK-RECONCILIATION-' || task.id
                  AND result.reserved_quantity = source.reserved_quantity
                  AND result.on_hand_quantity = source.on_hand_quantity
                      - COALESCE((
                          SELECT SUM(previous.quantity)
                          FROM inventory_movements AS previous
                          WHERE previous.source_snapshot_id = source.id
                      ), 0)
                      - NEW.quantity
            )
            BEGIN
                SELECT RAISE(ABORT, 'inventory movement lineage or quantity conservation is invalid');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_movement_lineage_guard "
            "ON inventory_movements"
        )
        op.execute("DROP FUNCTION IF EXISTS enforce_inventory_movement_lineage()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_lineage_guard")
