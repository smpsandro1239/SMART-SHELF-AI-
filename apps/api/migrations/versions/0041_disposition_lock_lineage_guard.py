"""Validate disposition lineage before acquiring the source-image lock."""

from alembic import op


revision = "0041_disposition_lock_lineage_guard"
down_revision = "0040_disposition_image_lock_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION lock_shelf_image_before_artifact_disposition_event()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                reference_image_id INTEGER;
                reference_store_id INTEGER;
            BEGIN
                /* Artifact references are append-only. Read the immutable lineage
                   first, reject mismatches, then lock image before reference. */
                SELECT shelf_image_id, store_id
                INTO reference_image_id, reference_store_id
                FROM shelf_image_artifact_references
                WHERE id = NEW.artifact_reference_id;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'artifact disposition reference does not exist'
                        USING ERRCODE = '23503';
                END IF;

                IF reference_image_id IS DISTINCT FROM NEW.shelf_image_id
                   OR reference_store_id IS DISTINCT FROM NEW.store_id THEN
                    RAISE EXCEPTION 'artifact disposition lineage does not match its immutable reference'
                        USING ERRCODE = '23514';
                END IF;

                PERFORM 1
                FROM shelf_images
                WHERE id = reference_image_id
                FOR UPDATE;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'artifact disposition source image does not exist'
                        USING ERRCODE = '23503';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_00_artifact_disposition_validate_reference_lineage
            BEFORE INSERT ON shelf_image_artifact_disposition_events
            WHEN NOT EXISTS (
                SELECT 1
                FROM shelf_image_artifact_references
                WHERE id = NEW.artifact_reference_id
                  AND shelf_image_id = NEW.shelf_image_id
                  AND store_id = NEW.store_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'artifact disposition lineage does not match its immutable reference');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_00_artifact_disposition_validate_reference_lineage"
        )
    # PostgreSQL function replacement is removed by the preceding migration
    # when the complete 0041 -> 0040 chain is downgraded.
