"""Enforce store ownership of external artifact records at the database boundary.

Artifact references and signed inventory snapshots duplicate store_id for
efficient tenant-scoped queries. The value must always match the store reached
through shelf_image -> shelf -> zone, even for direct SQL writes.
"""
from alembic import op
import sqlalchemy as sa


revision = "0048_artifact_store_lineage_guard"
down_revision = "0047_artifact_inventory_key_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inconsistent = bind.execute(sa.text("""
        SELECT COUNT(*)
        FROM shelf_image_artifact_references r
        JOIN shelf_images i ON i.id = r.shelf_image_id
        JOIN shelves s ON s.id = i.shelf_id
        JOIN zones z ON z.id = s.zone_id
        WHERE r.store_id <> z.store_id
    """)).scalar_one()
    inconsistent += bind.execute(sa.text("""
        SELECT COUNT(*)
        FROM shelf_image_artifact_inventory_snapshots r
        JOIN shelf_images i ON i.id = r.shelf_image_id
        JOIN shelves s ON s.id = i.shelf_id
        JOIN zones z ON z.id = s.zone_id
        WHERE r.store_id <> z.store_id
    """)).scalar_one()
    if inconsistent:
        raise RuntimeError(
            "Cannot enable artifact store-lineage guard: "
            f"{inconsistent} persisted artifact records have mismatched stores"
        )

    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION enforce_artifact_record_store_lineage()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM shelf_images i
                    JOIN shelves s ON s.id = i.shelf_id
                    JOIN zones z ON z.id = s.zone_id
                    WHERE i.id = NEW.shelf_image_id
                      AND z.store_id = NEW.store_id
                ) THEN
                    RAISE EXCEPTION 'artifact store does not match shelf image store'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_artifact_reference_store_lineage
            BEFORE INSERT OR UPDATE OF shelf_image_id, store_id
            ON shelf_image_artifact_references
            FOR EACH ROW
            EXECUTE FUNCTION enforce_artifact_record_store_lineage()
        """)
        op.execute("""
            CREATE TRIGGER trg_artifact_inventory_store_lineage
            BEFORE INSERT OR UPDATE OF shelf_image_id, store_id
            ON shelf_image_artifact_inventory_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION enforce_artifact_record_store_lineage()
        """)
    elif bind.dialect.name == "sqlite":
        for table, prefix in (
            ("shelf_image_artifact_references", "artifact_reference"),
            ("shelf_image_artifact_inventory_snapshots", "artifact_inventory"),
        ):
            for operation, event in (("insert", "INSERT"), ("update", "UPDATE OF shelf_image_id, store_id")):
                op.execute(f"""
                    CREATE TRIGGER trg_{prefix}_store_lineage_{operation}
                    BEFORE {event} ON {table}
                    WHEN NOT EXISTS (
                        SELECT 1
                        FROM shelf_images i
                        JOIN shelves s ON s.id = i.shelf_id
                        JOIN zones z ON z.id = s.zone_id
                        WHERE i.id = NEW.shelf_image_id
                          AND z.store_id = NEW.store_id
                    )
                    BEGIN
                        SELECT RAISE(ABORT, 'artifact store does not match shelf image store');
                    END
                """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_artifact_reference_store_lineage "
            "ON shelf_image_artifact_references"
        )
        op.execute(
            "DROP TRIGGER IF EXISTS trg_artifact_inventory_store_lineage "
            "ON shelf_image_artifact_inventory_snapshots"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS enforce_artifact_record_store_lineage()"
        )
    elif bind.dialect.name == "sqlite":
        for name in (
            "trg_artifact_reference_store_lineage_insert",
            "trg_artifact_reference_store_lineage_update",
            "trg_artifact_inventory_store_lineage_insert",
            "trg_artifact_inventory_store_lineage_update",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
