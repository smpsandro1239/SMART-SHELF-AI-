"""Serialize direct disposition-event inserts with image inventory workflows."""

from alembic import op


revision = "0040_disposition_image_lock_order"
down_revision = "0039_inventory_snapshot_monotonicity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION lock_shelf_image_before_artifact_disposition_event()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                /* Match API lock order: image -> artifact reference -> event history. */
                PERFORM 1
                FROM shelf_images
                WHERE id = NEW.shelf_image_id
                FOR UPDATE;

                IF NOT FOUND THEN
                    RAISE EXCEPTION 'artifact disposition source image does not exist'
                        USING ERRCODE = '23503';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        /* PostgreSQL orders same-timing triggers by name. This must run before
           trg_shelf_image_artifact_disposition_event_validate, which locks the
           artifact-reference row and validates the event sequence. */
        op.execute("""
            CREATE TRIGGER trg_00_artifact_disposition_lock_image
            BEFORE INSERT ON shelf_image_artifact_disposition_events
            FOR EACH ROW
            EXECUTE FUNCTION lock_shelf_image_before_artifact_disposition_event()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_00_artifact_disposition_validate_image
            BEFORE INSERT ON shelf_image_artifact_disposition_events
            WHEN NOT EXISTS (
                SELECT 1 FROM shelf_images WHERE id = NEW.shelf_image_id
            )
            BEGIN
                SELECT RAISE(ABORT, 'artifact disposition source image does not exist');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_00_artifact_disposition_lock_image "
            "ON shelf_image_artifact_disposition_events"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS lock_shelf_image_before_artifact_disposition_event()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_00_artifact_disposition_validate_image")
