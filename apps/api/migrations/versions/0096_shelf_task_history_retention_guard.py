"""Prevent cascading deletion of shelf/zone entities with task history."""
from alembic import op

revision = "0096_shelf_task_history_retention_guard"
down_revision = "0095_inventory_movement_destination_zone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_shelf_delete_with_task_history_0096()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM replenishment_tasks AS task
                    WHERE task.shelf_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'shelf has replenishment task history'
                        USING ERRCODE = '23503';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_task_history_retention_0096
            BEFORE DELETE ON shelves
            FOR EACH ROW EXECUTE FUNCTION prevent_shelf_delete_with_task_history_0096()
        """)
        op.execute("""
            CREATE FUNCTION prevent_zone_delete_with_task_history_0096()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM shelves AS shelf
                    JOIN replenishment_tasks AS task ON task.shelf_id = shelf.id
                    WHERE shelf.zone_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'zone has replenishment task history'
                        USING ERRCODE = '23503';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_zone_task_history_retention_0096
            BEFORE DELETE ON zones
            FOR EACH ROW EXECUTE FUNCTION prevent_zone_delete_with_task_history_0096()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_task_history_retention_0096
            BEFORE DELETE ON shelves
            WHEN EXISTS (
                SELECT 1 FROM replenishment_tasks AS task
                WHERE task.shelf_id = OLD.id
            )
            BEGIN
                SELECT RAISE(ABORT, 'shelf has replenishment task history');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_zone_task_history_retention_0096
            BEFORE DELETE ON zones
            WHEN EXISTS (
                SELECT 1
                FROM shelves AS shelf
                JOIN replenishment_tasks AS task ON task.shelf_id = shelf.id
                WHERE shelf.zone_id = OLD.id
            )
            BEGIN
                SELECT RAISE(ABORT, 'zone has replenishment task history');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_zone_task_history_retention_0096 ON zones")
        op.execute("DROP FUNCTION IF EXISTS prevent_zone_delete_with_task_history_0096()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_task_history_retention_0096 ON shelves")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_delete_with_task_history_0096()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_zone_task_history_retention_0096")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_task_history_retention_0096")
