"""Prevent moving shelf-image lineage after external artifacts are recorded."""

from alembic import op

revision = "0038_artifact_lineage_immutable"
down_revision = "0037_embedding_exemplar_lineage_immutable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_zone_store_change_with_artifacts()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NEW.store_id IS DISTINCT FROM OLD.store_id AND EXISTS (
                    SELECT 1
                    FROM shelves sh
                    JOIN shelf_images si ON si.shelf_id = sh.id
                    WHERE sh.zone_id = OLD.id
                      AND (
                        EXISTS (SELECT 1 FROM shelf_image_artifact_references ar WHERE ar.shelf_image_id = si.id)
                        OR EXISTS (SELECT 1 FROM shelf_image_artifact_inventory_snapshots snap WHERE snap.shelf_image_id = si.id)
                      )
                ) THEN
                    RAISE EXCEPTION 'zone store cannot change while shelf images have external artifact history'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE FUNCTION prevent_shelf_zone_change_with_artifacts()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NEW.zone_id IS DISTINCT FROM OLD.zone_id AND EXISTS (
                    SELECT 1 FROM shelf_images si
                    WHERE si.shelf_id = OLD.id
                      AND (
                        EXISTS (SELECT 1 FROM shelf_image_artifact_references ar WHERE ar.shelf_image_id = si.id)
                        OR EXISTS (SELECT 1 FROM shelf_image_artifact_inventory_snapshots snap WHERE snap.shelf_image_id = si.id)
                      )
                ) THEN
                    RAISE EXCEPTION 'shelf zone cannot change while shelf images have external artifact history'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE FUNCTION prevent_image_shelf_change_with_artifacts()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NEW.shelf_id IS DISTINCT FROM OLD.shelf_id AND (
                    EXISTS (SELECT 1 FROM shelf_image_artifact_references ar WHERE ar.shelf_image_id = OLD.id)
                    OR EXISTS (SELECT 1 FROM shelf_image_artifact_inventory_snapshots snap WHERE snap.shelf_image_id = OLD.id)
                ) THEN
                    RAISE EXCEPTION 'shelf image shelf cannot change while external artifact history exists'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_zones_artifact_lineage_immutable
            BEFORE UPDATE OF store_id ON zones
            FOR EACH ROW EXECUTE FUNCTION prevent_zone_store_change_with_artifacts()
        """)
        op.execute("""
            CREATE TRIGGER trg_shelves_artifact_lineage_immutable
            BEFORE UPDATE OF zone_id ON shelves
            FOR EACH ROW EXECUTE FUNCTION prevent_shelf_zone_change_with_artifacts()
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_images_artifact_lineage_immutable
            BEFORE UPDATE OF shelf_id ON shelf_images
            FOR EACH ROW EXECUTE FUNCTION prevent_image_shelf_change_with_artifacts()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_zones_artifact_lineage_immutable
            BEFORE UPDATE OF store_id ON zones
            WHEN NEW.store_id <> OLD.store_id AND EXISTS (
                SELECT 1
                FROM shelves sh
                JOIN shelf_images si ON si.shelf_id = sh.id
                WHERE sh.zone_id = OLD.id
                  AND (
                    EXISTS (SELECT 1 FROM shelf_image_artifact_references ar WHERE ar.shelf_image_id = si.id)
                    OR EXISTS (SELECT 1 FROM shelf_image_artifact_inventory_snapshots snap WHERE snap.shelf_image_id = si.id)
                  )
            )
            BEGIN
                SELECT RAISE(ABORT, 'zone store cannot change while shelf images have external artifact history');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelves_artifact_lineage_immutable
            BEFORE UPDATE OF zone_id ON shelves
            WHEN NEW.zone_id <> OLD.zone_id AND EXISTS (
                SELECT 1 FROM shelf_images si
                WHERE si.shelf_id = OLD.id
                  AND (
                    EXISTS (SELECT 1 FROM shelf_image_artifact_references ar WHERE ar.shelf_image_id = si.id)
                    OR EXISTS (SELECT 1 FROM shelf_image_artifact_inventory_snapshots snap WHERE snap.shelf_image_id = si.id)
                  )
            )
            BEGIN
                SELECT RAISE(ABORT, 'shelf zone cannot change while shelf images have external artifact history');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_images_artifact_lineage_immutable
            BEFORE UPDATE OF shelf_id ON shelf_images
            WHEN NEW.shelf_id <> OLD.shelf_id AND (
                EXISTS (SELECT 1 FROM shelf_image_artifact_references ar WHERE ar.shelf_image_id = OLD.id)
                OR EXISTS (SELECT 1 FROM shelf_image_artifact_inventory_snapshots snap WHERE snap.shelf_image_id = OLD.id)
            )
            BEGIN
                SELECT RAISE(ABORT, 'shelf image shelf cannot change while external artifact history exists');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    for trigger in (
        "trg_zones_artifact_lineage_immutable",
        "trg_shelves_artifact_lineage_immutable",
        "trg_shelf_images_artifact_lineage_immutable",
    ):
        if bind.dialect.name == "postgresql":
            table = {
                "trg_zones_artifact_lineage_immutable": "zones",
                "trg_shelves_artifact_lineage_immutable": "shelves",
                "trg_shelf_images_artifact_lineage_immutable": "shelf_images",
            }[trigger]
            op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
        elif bind.dialect.name == "sqlite":
            op.execute(f"DROP TRIGGER IF EXISTS {trigger}")

    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS prevent_image_shelf_change_with_artifacts()")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_zone_change_with_artifacts()")
        op.execute("DROP FUNCTION IF EXISTS prevent_zone_store_change_with_artifacts()")
