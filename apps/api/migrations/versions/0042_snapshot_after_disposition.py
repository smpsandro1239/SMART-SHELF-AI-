"""Require inventory snapshots to postdate every disposition event for the image/source."""

from alembic import op


revision = "0042_snapshot_after_disposition"
down_revision = "0041_disposition_lock_lineage_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION enforce_artifact_snapshot_after_disposition()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                latest_disposition_at TIMESTAMPTZ;
            BEGIN
                /* The 0038/0039 triggers have already locked the image.
                   Event writers use the same image-first lock order. */
                SELECT MAX(event.created_at)
                INTO latest_disposition_at
                FROM shelf_image_artifact_disposition_events event
                JOIN shelf_image_artifact_references reference
                  ON reference.id = event.artifact_reference_id
                WHERE reference.shelf_image_id = NEW.shelf_image_id
                  AND reference.store_id = NEW.store_id
                  AND reference.external_system = NEW.external_system;

                IF latest_disposition_at IS NOT NULL
                   AND NEW.generated_at <= latest_disposition_at THEN
                    RAISE EXCEPTION 'artifact inventory snapshot must strictly postdate disposition history'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_z_artifact_snapshot_after_disposition
            BEFORE INSERT ON shelf_image_artifact_inventory_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION enforce_artifact_snapshot_after_disposition()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_z_artifact_snapshot_after_disposition
            BEFORE INSERT ON shelf_image_artifact_inventory_snapshots
            WHEN EXISTS (
                SELECT 1
                FROM shelf_image_artifact_disposition_events event
                JOIN shelf_image_artifact_references reference
                  ON reference.id = event.artifact_reference_id
                WHERE reference.shelf_image_id = NEW.shelf_image_id
                  AND reference.store_id = NEW.store_id
                  AND reference.external_system = NEW.external_system
                  AND julianday(NEW.generated_at) <= julianday(event.created_at)
            )
            BEGIN
                SELECT RAISE(ABORT, 'artifact inventory snapshot must strictly postdate disposition history');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_z_artifact_snapshot_after_disposition "
            "ON shelf_image_artifact_inventory_snapshots"
        )
        op.execute("DROP FUNCTION IF EXISTS enforce_artifact_snapshot_after_disposition()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_z_artifact_snapshot_after_disposition")
