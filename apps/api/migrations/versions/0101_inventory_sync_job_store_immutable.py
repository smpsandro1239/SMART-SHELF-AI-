"""Make the tenant identity of ERP/WMS synchronization jobs immutable."""

from alembic import op


revision = "0101_inventory_sync_job_store_immutable"
down_revision = "0100_embedding_source_image_shelf_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_inventory_sync_job_store_change_0101()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NEW.store_id IS DISTINCT FROM OLD.store_id THEN
                    RAISE EXCEPTION 'inventory sync job store_id is immutable'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_sync_job_store_immutable_0101
            BEFORE UPDATE OF store_id ON inventory_sync_jobs
            FOR EACH ROW EXECUTE FUNCTION prevent_inventory_sync_job_store_change_0101()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_sync_job_store_immutable_0101
            BEFORE UPDATE OF store_id ON inventory_sync_jobs
            WHEN NEW.store_id IS NOT OLD.store_id
            BEGIN
                SELECT RAISE(ABORT, 'inventory sync job store_id is immutable');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_sync_job_store_immutable_0101 "
            "ON inventory_sync_jobs"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS prevent_inventory_sync_job_store_change_0101()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_sync_job_store_immutable_0101"
        )
