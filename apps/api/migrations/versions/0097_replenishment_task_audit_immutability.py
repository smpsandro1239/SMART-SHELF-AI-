"""Make replenishment task audit events append-only and task identity immutable."""
from alembic import op

revision = "0097_replenishment_task_audit_immutability"
down_revision = "0096_shelf_task_history_retention_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_replenishment_task_event_mutation_0097()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'replenishment task events are append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_replenishment_task_event_append_only_0097
            BEFORE UPDATE OR DELETE ON replenishment_task_events
            FOR EACH ROW EXECUTE FUNCTION prevent_replenishment_task_event_mutation_0097()
        """)
        op.execute("""
            CREATE FUNCTION prevent_replenishment_task_delete_with_audit_0097()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM replenishment_task_events AS event
                    WHERE event.task_id = OLD.id
                ) THEN
                    RAISE EXCEPTION 'replenishment task has audit history'
                        USING ERRCODE = '23503';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_replenishment_task_delete_audit_guard_0097
            BEFORE DELETE ON replenishment_tasks
            FOR EACH ROW EXECUTE FUNCTION prevent_replenishment_task_delete_with_audit_0097()
        """)
        op.execute("""
            CREATE FUNCTION prevent_replenishment_task_identity_change_0097()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF (NEW.store_id, NEW.shelf_id, NEW.product_id)
                   IS DISTINCT FROM
                   (OLD.store_id, OLD.shelf_id, OLD.product_id)
                   AND EXISTS (
                       SELECT 1 FROM replenishment_task_events AS event
                       WHERE event.task_id = OLD.id
                   ) THEN
                    RAISE EXCEPTION 'replenishment task identity is immutable after audit begins'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_replenishment_task_identity_guard_0097
            BEFORE UPDATE OF store_id, shelf_id, product_id ON replenishment_tasks
            FOR EACH ROW EXECUTE FUNCTION prevent_replenishment_task_identity_change_0097()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_replenishment_task_event_update_guard_0097
            BEFORE UPDATE ON replenishment_task_events
            BEGIN SELECT RAISE(ABORT, 'replenishment task events are append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_replenishment_task_event_delete_guard_0097
            BEFORE DELETE ON replenishment_task_events
            BEGIN SELECT RAISE(ABORT, 'replenishment task events are append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_replenishment_task_delete_audit_guard_0097
            BEFORE DELETE ON replenishment_tasks
            WHEN EXISTS (
                SELECT 1 FROM replenishment_task_events AS event
                WHERE event.task_id = OLD.id
            )
            BEGIN SELECT RAISE(ABORT, 'replenishment task has audit history'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_replenishment_task_identity_guard_0097
            BEFORE UPDATE OF store_id, shelf_id, product_id ON replenishment_tasks
            WHEN (NEW.store_id <> OLD.store_id OR NEW.shelf_id <> OLD.shelf_id OR NEW.product_id <> OLD.product_id)
             AND EXISTS (
                SELECT 1 FROM replenishment_task_events AS event
                WHERE event.task_id = OLD.id
             )
            BEGIN SELECT RAISE(ABORT, 'replenishment task identity is immutable after audit begins'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_replenishment_task_identity_guard_0097 ON replenishment_tasks")
        op.execute("DROP FUNCTION IF EXISTS prevent_replenishment_task_identity_change_0097()")
        op.execute("DROP TRIGGER IF EXISTS trg_replenishment_task_delete_audit_guard_0097 ON replenishment_tasks")
        op.execute("DROP FUNCTION IF EXISTS prevent_replenishment_task_delete_with_audit_0097()")
        op.execute("DROP TRIGGER IF EXISTS trg_replenishment_task_event_append_only_0097 ON replenishment_task_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_replenishment_task_event_mutation_0097()")
    elif bind.dialect.name == "sqlite":
        for name in (
            "trg_replenishment_task_identity_guard_0097",
            "trg_replenishment_task_delete_audit_guard_0097",
            "trg_replenishment_task_event_delete_guard_0097",
            "trg_replenishment_task_event_update_guard_0097",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
