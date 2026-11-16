"""Enforce tenant lineage for shelf-scoped operational records.

Observation alerts, capture sessions and replenishment tasks duplicate store_id
for tenant-scoped queries. Their store must match the tenant reached through
shelf -> zone. Moving a shelf or zone must not invalidate those records.
"""
from alembic import op
import sqlalchemy as sa


revision = "0050_shelf_record_store_lineage_guard"
down_revision = "0049_artifact_upstream_store_lineage_guard"
branch_labels = None
depends_on = None

_TABLES = ("observation_alerts", "capture_sessions", "replenishment_tasks")


def upgrade() -> None:
    bind = op.get_bind()

    inconsistent = 0
    for table in _TABLES:
        inconsistent += bind.execute(sa.text(f"""
            SELECT COUNT(*)
            FROM {table} record
            JOIN shelves shelf ON shelf.id = record.shelf_id
            JOIN zones zone ON zone.id = shelf.zone_id
            WHERE record.store_id <> zone.store_id
        """)).scalar_one()
    if inconsistent:
        raise RuntimeError(
            "Cannot enable shelf record store-lineage guard: "
            f"{inconsistent} persisted records have mismatched stores"
        )

    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION enforce_shelf_record_store_lineage()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM shelves shelf
                    JOIN zones zone ON zone.id = shelf.zone_id
                    WHERE shelf.id = NEW.shelf_id
                      AND zone.store_id = NEW.store_id
                ) THEN
                    RAISE EXCEPTION 'shelf record store does not match shelf store'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        for table in _TABLES:
            op.execute(f"""
                CREATE TRIGGER trg_{table}_store_lineage
                BEFORE INSERT OR UPDATE OF shelf_id, store_id ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION enforce_shelf_record_store_lineage()
            """)

        op.execute("""
            CREATE FUNCTION prevent_shelf_record_upstream_store_change()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                target_store_id INTEGER;
                has_mismatch BOOLEAN;
            BEGIN
                IF TG_TABLE_NAME = 'zones' THEN
                    target_store_id := NEW.store_id;
                    SELECT EXISTS (
                        SELECT 1 FROM shelves shelf
                        JOIN observation_alerts alert ON alert.shelf_id = shelf.id
                        WHERE shelf.zone_id = OLD.id AND alert.store_id <> target_store_id
                        UNION ALL
                        SELECT 1 FROM shelves shelf
                        JOIN capture_sessions session ON session.shelf_id = shelf.id
                        WHERE shelf.zone_id = OLD.id AND session.store_id <> target_store_id
                        UNION ALL
                        SELECT 1 FROM shelves shelf
                        JOIN replenishment_tasks task ON task.shelf_id = shelf.id
                        WHERE shelf.zone_id = OLD.id AND task.store_id <> target_store_id
                    ) INTO has_mismatch;
                ELSE
                    SELECT store_id INTO target_store_id FROM zones WHERE id = NEW.zone_id;
                    SELECT EXISTS (
                        SELECT 1 FROM observation_alerts WHERE shelf_id = OLD.id AND store_id <> target_store_id
                        UNION ALL
                        SELECT 1 FROM capture_sessions WHERE shelf_id = OLD.id AND store_id <> target_store_id
                        UNION ALL
                        SELECT 1 FROM replenishment_tasks WHERE shelf_id = OLD.id AND store_id <> target_store_id
                    ) INTO has_mismatch;
                END IF;

                IF has_mismatch THEN
                    RAISE EXCEPTION 'cannot move shelf hierarchy across stores while shelf records exist'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_zone_shelf_record_store_lineage
            BEFORE UPDATE OF store_id ON zones
            FOR EACH ROW WHEN (NEW.store_id IS DISTINCT FROM OLD.store_id)
            EXECUTE FUNCTION prevent_shelf_record_upstream_store_change()
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_shelf_record_store_lineage
            BEFORE UPDATE OF zone_id ON shelves
            FOR EACH ROW WHEN (NEW.zone_id IS DISTINCT FROM OLD.zone_id)
            EXECUTE FUNCTION prevent_shelf_record_upstream_store_change()
        """)
    elif bind.dialect.name == "sqlite":
        for table in _TABLES:
            op.execute(f"""
                CREATE TRIGGER trg_{table}_store_lineage_insert
                BEFORE INSERT ON {table}
                WHEN NOT EXISTS (
                    SELECT 1 FROM shelves shelf
                    JOIN zones zone ON zone.id = shelf.zone_id
                    WHERE shelf.id = NEW.shelf_id
                      AND zone.store_id = NEW.store_id
                )
                BEGIN
                    SELECT RAISE(ABORT, 'shelf record store does not match shelf store');
                END
            """)
            op.execute(f"""
                CREATE TRIGGER trg_{table}_store_lineage_update
                BEFORE UPDATE OF shelf_id, store_id ON {table}
                WHEN NOT EXISTS (
                    SELECT 1 FROM shelves shelf
                    JOIN zones zone ON zone.id = shelf.zone_id
                    WHERE shelf.id = NEW.shelf_id
                      AND zone.store_id = NEW.store_id
                )
                BEGIN
                    SELECT RAISE(ABORT, 'shelf record store does not match shelf store');
                END
            """)

        op.execute("""
            CREATE TRIGGER trg_zone_shelf_record_store_lineage
            BEFORE UPDATE OF store_id ON zones
            WHEN NEW.store_id <> OLD.store_id AND (
                EXISTS (
                    SELECT 1 FROM shelves shelf
                    JOIN observation_alerts alert ON alert.shelf_id = shelf.id
                    WHERE shelf.zone_id = OLD.id AND alert.store_id <> NEW.store_id
                )
                OR EXISTS (
                    SELECT 1 FROM shelves shelf
                    JOIN capture_sessions session ON session.shelf_id = shelf.id
                    WHERE shelf.zone_id = OLD.id AND session.store_id <> NEW.store_id
                )
                OR EXISTS (
                    SELECT 1 FROM shelves shelf
                    JOIN replenishment_tasks task ON task.shelf_id = shelf.id
                    WHERE shelf.zone_id = OLD.id AND task.store_id <> NEW.store_id
                )
            )
            BEGIN
                SELECT RAISE(ABORT, 'cannot move shelf hierarchy across stores while shelf records exist');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_shelf_record_store_lineage
            BEFORE UPDATE OF zone_id ON shelves
            WHEN NEW.zone_id <> OLD.zone_id AND (
                EXISTS (SELECT 1 FROM observation_alerts WHERE shelf_id = OLD.id AND store_id <> (SELECT store_id FROM zones WHERE id = NEW.zone_id))
                OR EXISTS (SELECT 1 FROM capture_sessions WHERE shelf_id = OLD.id AND store_id <> (SELECT store_id FROM zones WHERE id = NEW.zone_id))
                OR EXISTS (SELECT 1 FROM replenishment_tasks WHERE shelf_id = OLD.id AND store_id <> (SELECT store_id FROM zones WHERE id = NEW.zone_id))
            )
            BEGIN
                SELECT RAISE(ABORT, 'cannot move shelf hierarchy across stores while shelf records exist');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_zone_shelf_record_store_lineage ON zones")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_shelf_record_store_lineage ON shelves")
        for table in _TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_store_lineage ON {table}")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_record_upstream_store_change()")
        op.execute("DROP FUNCTION IF EXISTS enforce_shelf_record_store_lineage()")
    elif bind.dialect.name == "sqlite":
        names = [
            "trg_zone_shelf_record_store_lineage",
            "trg_shelf_shelf_record_store_lineage",
        ]
        for table in _TABLES:
            names.extend((f"trg_{table}_store_lineage_insert", f"trg_{table}_store_lineage_update"))
        for name in names:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
