"""Protect artifact tenant lineage when parent shelf hierarchy is moved.

0048 validated artifact rows on write. This migration closes the reverse path:
moving a zone, shelf, or image must not silently change the effective tenant
of already-declared artifacts or signed inventory snapshots.
"""
from alembic import op


revision = "0049_artifact_upstream_store_lineage_guard"
down_revision = "0048_artifact_store_lineage_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_artifact_upstream_store_lineage_change()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                target_store_id INTEGER;
            BEGIN
                IF TG_TABLE_NAME = 'zones' THEN
                    target_store_id := NEW.store_id;
                    IF EXISTS (
                        SELECT 1
                        FROM shelves s
                        JOIN shelf_images i ON i.shelf_id = s.id
                        LEFT JOIN shelf_image_artifact_references r ON r.shelf_image_id = i.id
                        LEFT JOIN shelf_image_artifact_inventory_snapshots n ON n.shelf_image_id = i.id
                        WHERE s.zone_id = OLD.id
                          AND (r.store_id IS NOT NULL AND r.store_id <> target_store_id
                               OR n.store_id IS NOT NULL AND n.store_id <> target_store_id)
                    ) THEN
                        RAISE EXCEPTION 'cannot move zone across stores while artifact records exist'
                            USING ERRCODE = '23514';
                    END IF;
                ELSIF TG_TABLE_NAME = 'shelves' THEN
                    SELECT store_id INTO target_store_id FROM zones WHERE id = NEW.zone_id;
                    IF EXISTS (
                        SELECT 1
                        FROM shelf_images i
                        LEFT JOIN shelf_image_artifact_references r ON r.shelf_image_id = i.id
                        LEFT JOIN shelf_image_artifact_inventory_snapshots n ON n.shelf_image_id = i.id
                        WHERE i.shelf_id = OLD.id
                          AND (r.store_id IS NOT NULL AND r.store_id <> target_store_id
                               OR n.store_id IS NOT NULL AND n.store_id <> target_store_id)
                    ) THEN
                        RAISE EXCEPTION 'cannot move shelf across stores while artifact records exist'
                            USING ERRCODE = '23514';
                    END IF;
                ELSIF TG_TABLE_NAME = 'shelf_images' THEN
                    SELECT z.store_id INTO target_store_id
                    FROM shelves s JOIN zones z ON z.id = s.zone_id
                    WHERE s.id = NEW.shelf_id;
                    IF EXISTS (
                        SELECT 1 FROM shelf_image_artifact_references r
                        WHERE r.shelf_image_id = OLD.id AND r.store_id <> target_store_id
                    ) OR EXISTS (
                        SELECT 1 FROM shelf_image_artifact_inventory_snapshots n
                        WHERE n.shelf_image_id = OLD.id AND n.store_id <> target_store_id
                    ) THEN
                        RAISE EXCEPTION 'cannot move image across stores while artifact records exist'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_zone_artifact_store_lineage_immutable
            BEFORE UPDATE OF store_id ON zones
            FOR EACH ROW WHEN (NEW.store_id IS DISTINCT FROM OLD.store_id)
            EXECUTE FUNCTION prevent_artifact_upstream_store_lineage_change()
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_artifact_store_lineage_immutable
            BEFORE UPDATE OF zone_id ON shelves
            FOR EACH ROW WHEN (NEW.zone_id IS DISTINCT FROM OLD.zone_id)
            EXECUTE FUNCTION prevent_artifact_upstream_store_lineage_change()
        """)
        op.execute("""
            CREATE TRIGGER trg_image_artifact_store_lineage_immutable
            BEFORE UPDATE OF shelf_id ON shelf_images
            FOR EACH ROW WHEN (NEW.shelf_id IS DISTINCT FROM OLD.shelf_id)
            EXECUTE FUNCTION prevent_artifact_upstream_store_lineage_change()
        """)
    elif bind.dialect.name == "sqlite":
        statements = [
            """
            CREATE TRIGGER trg_zone_artifact_store_lineage_immutable
            BEFORE UPDATE OF store_id ON zones
            WHEN NEW.store_id <> OLD.store_id AND EXISTS (
                SELECT 1 FROM shelves s
                JOIN shelf_images i ON i.shelf_id = s.id
                LEFT JOIN shelf_image_artifact_references r ON r.shelf_image_id = i.id
                LEFT JOIN shelf_image_artifact_inventory_snapshots n ON n.shelf_image_id = i.id
                WHERE s.zone_id = OLD.id
                  AND (r.store_id IS NOT NULL AND r.store_id <> NEW.store_id
                       OR n.store_id IS NOT NULL AND n.store_id <> NEW.store_id)
            )
            BEGIN SELECT RAISE(ABORT, 'cannot move zone across stores while artifact records exist'); END
            """,
            """
            CREATE TRIGGER trg_shelf_artifact_store_lineage_immutable
            BEFORE UPDATE OF zone_id ON shelves
            WHEN NEW.zone_id <> OLD.zone_id AND EXISTS (
                SELECT 1 FROM shelf_images i
                LEFT JOIN shelf_image_artifact_references r ON r.shelf_image_id = i.id
                LEFT JOIN shelf_image_artifact_inventory_snapshots n ON n.shelf_image_id = i.id
                WHERE i.shelf_id = OLD.id
                  AND (r.store_id IS NOT NULL AND r.store_id <> (SELECT store_id FROM zones WHERE id = NEW.zone_id)
                       OR n.store_id IS NOT NULL AND n.store_id <> (SELECT store_id FROM zones WHERE id = NEW.zone_id))
            )
            BEGIN SELECT RAISE(ABORT, 'cannot move shelf across stores while artifact records exist'); END
            """,
            """
            CREATE TRIGGER trg_image_artifact_store_lineage_immutable
            BEFORE UPDATE OF shelf_id ON shelf_images
            WHEN NEW.shelf_id <> OLD.shelf_id AND (
                EXISTS (
                    SELECT 1 FROM shelf_image_artifact_references r
                    WHERE r.shelf_image_id = OLD.id
                      AND r.store_id <> (SELECT z.store_id FROM shelves s JOIN zones z ON z.id = s.zone_id WHERE s.id = NEW.shelf_id)
                )
                OR EXISTS (
                    SELECT 1 FROM shelf_image_artifact_inventory_snapshots n
                    WHERE n.shelf_image_id = OLD.id
                      AND n.store_id <> (SELECT z.store_id FROM shelves s JOIN zones z ON z.id = s.zone_id WHERE s.id = NEW.shelf_id)
                )
            )
            BEGIN SELECT RAISE(ABORT, 'cannot move image across stores while artifact records exist'); END
            """,
        ]
        for statement in statements:
            op.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_zone_artifact_store_lineage_immutable ON zones")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_artifact_store_lineage_immutable ON shelves")
        op.execute("DROP TRIGGER IF EXISTS trg_image_artifact_store_lineage_immutable ON shelf_images")
        op.execute("DROP FUNCTION IF EXISTS prevent_artifact_upstream_store_lineage_change()")
    elif bind.dialect.name == "sqlite":
        for name in (
            "trg_zone_artifact_store_lineage_immutable",
            "trg_shelf_artifact_store_lineage_immutable",
            "trg_image_artifact_store_lineage_immutable",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
