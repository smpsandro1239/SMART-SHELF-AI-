"""Enforce monotonic artifact inventory snapshot time at the database boundary."""

from alembic import op

revision = "0039_inventory_snapshot_monotonicity"
down_revision = "0038_artifact_lineage_immutable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION enforce_artifact_inventory_snapshot_monotonicity()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                latest_generated_at TIMESTAMPTZ;
            BEGIN
                /* Serialize all writers for this image before checking source history. */
                PERFORM 1
                FROM shelf_images
                WHERE id = NEW.shelf_image_id
                FOR UPDATE;

                SELECT MAX(generated_at)
                INTO latest_generated_at
                FROM shelf_image_artifact_inventory_snapshots
                WHERE shelf_image_id = NEW.shelf_image_id
                  AND store_id = NEW.store_id
                  AND external_system = NEW.external_system;

                IF latest_generated_at IS NOT NULL
                   AND NEW.generated_at <= latest_generated_at THEN
                    RAISE EXCEPTION 'artifact inventory snapshot must be newer than the latest accepted snapshot'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_artifact_snapshot_temporal_monotonic
            BEFORE INSERT ON shelf_image_artifact_inventory_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION enforce_artifact_inventory_snapshot_monotonicity()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_artifact_snapshot_temporal_monotonic
            BEFORE INSERT ON shelf_image_artifact_inventory_snapshots
            WHEN EXISTS (
                SELECT 1
                FROM shelf_image_artifact_inventory_snapshots existing
                WHERE existing.shelf_image_id = NEW.shelf_image_id
                  AND existing.store_id = NEW.store_id
                  AND existing.external_system = NEW.external_system
                  AND julianday(NEW.generated_at) <= julianday(existing.generated_at)
            )
            BEGIN
                SELECT RAISE(ABORT, 'artifact inventory snapshot must be newer than the latest accepted snapshot');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_artifact_snapshot_temporal_monotonic "
            "ON shelf_image_artifact_inventory_snapshots"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS enforce_artifact_inventory_snapshot_monotonicity()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_artifact_snapshot_temporal_monotonic")
