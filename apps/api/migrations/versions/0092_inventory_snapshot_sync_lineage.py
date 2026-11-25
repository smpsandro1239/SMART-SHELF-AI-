"""Link immutable inventory snapshots to their originating ERP/WMS sync run."""

from alembic import op
import sqlalchemy as sa

revision = "0092_inventory_snapshot_sync_lineage"
down_revision = "0091_inventory_manual_count_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inventory_snapshots",
        sa.Column("source_sync_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_inventory_snapshots_source_sync_id",
        "inventory_snapshots",
        ["source_sync_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_inventory_snapshots_source_sync_id",
            "inventory_snapshots",
            "inventory_source_syncs",
            ["source_sync_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        bind.exec_driver_sql("""
            CREATE FUNCTION guard_inventory_snapshot_source_sync_0092()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            DECLARE
                sync_store_id INTEGER;
                sync_source VARCHAR(8);
                sync_status VARCHAR(12);
            BEGIN
                IF NEW.source_sync_id IS NULL THEN
                    RETURN NEW;
                END IF;

                SELECT store_id, source, status
                INTO sync_store_id, sync_source, sync_status
                FROM inventory_source_syncs
                WHERE id = NEW.source_sync_id
                FOR SHARE;

                IF NOT FOUND
                   OR sync_store_id IS DISTINCT FROM NEW.store_id
                   OR sync_source IS DISTINCT FROM NEW.source
                   OR sync_status IS DISTINCT FROM 'STARTED' THEN
                    RAISE EXCEPTION 'inventory snapshot source_sync_id provenance mismatch';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        bind.exec_driver_sql("""
            CREATE TRIGGER trg_inventory_snapshot_source_sync_0092
            BEFORE INSERT ON inventory_snapshots
            FOR EACH ROW
            EXECUTE FUNCTION guard_inventory_snapshot_source_sync_0092()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_snapshot_source_sync_0092
            BEFORE INSERT ON inventory_snapshots
            WHEN NEW.source_sync_id IS NOT NULL
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1
                    FROM inventory_source_syncs s
                    WHERE s.id = NEW.source_sync_id
                      AND s.store_id = NEW.store_id
                      AND s.source = NEW.source
                      AND s.status = 'STARTED'
                )
                THEN RAISE(ABORT, 'inventory snapshot source_sync_id provenance mismatch')
                END;
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(
            "DROP TRIGGER IF EXISTS trg_inventory_snapshot_source_sync_0092 "
            "ON inventory_snapshots"
        )
        bind.exec_driver_sql(
            "DROP FUNCTION IF EXISTS guard_inventory_snapshot_source_sync_0092()"
        )
        op.drop_constraint(
            "fk_inventory_snapshots_source_sync_id",
            "inventory_snapshots",
            type_="foreignkey",
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_snapshot_source_sync_0092"
        )
    op.drop_index(
        "ix_inventory_snapshots_source_sync_id",
        table_name="inventory_snapshots",
    )
    op.drop_column("inventory_snapshots", "source_sync_id")
