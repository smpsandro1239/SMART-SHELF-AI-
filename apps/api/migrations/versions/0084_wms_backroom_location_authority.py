"""Add WMS physical-location provenance and per-store backroom authority."""
from alembic import op
import sqlalchemy as sa

revision = "0084_wms_backroom_location_authority"
down_revision = "0083_inventory_sync_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # Add columns without rebuilding inventory_snapshots: older SQLite databases
    # protect this append-only table with triggers that a batch rebuild could drop.
    op.add_column(
        "inventory_snapshots",
        sa.Column("location_code", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "inventory_snapshots",
        sa.Column(
            "availability_status",
            sa.String(length=16),
            nullable=False,
            server_default="UNKNOWN",
        ),
    )
    op.create_index(
        "ix_inventory_snapshot_backroom_lookup",
        "inventory_snapshots",
        ["store_id", "product_id", "source", "location_code", "availability_status", "captured_at"],
    )

    op.add_column(
        "inventory_freshness_policies",
        sa.Column("backroom_location_code", sa.String(length=120), nullable=True),
    )

    if dialect == "postgresql":
        bind.exec_driver_sql("""
            CREATE FUNCTION guard_inventory_snapshot_wms_provenance_0084()
            RETURNS trigger
            LANGUAGE plpgsql
            AS 'BEGIN
                IF NEW.source = ''WMS'' AND (
                    NEW.location_code IS NULL
                    OR length(trim(NEW.location_code)) = 0
                    OR NEW.availability_status NOT IN (''AVAILABLE'', ''UNAVAILABLE'')
                ) THEN
                    RAISE EXCEPTION ''new WMS snapshots require physical location and explicit availability'';
                END IF;
                RETURN NEW;
            END;'
        """)
        bind.exec_driver_sql("""
            CREATE TRIGGER trg_inventory_snapshot_wms_provenance_0084
            BEFORE INSERT ON inventory_snapshots
            FOR EACH ROW EXECUTE FUNCTION guard_inventory_snapshot_wms_provenance_0084()
        """)
        op.create_check_constraint(
            "ck_inventory_snapshot_availability_status",
            "inventory_snapshots",
            "availability_status IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN')",
        )
        op.create_check_constraint(
            "ck_inventory_snapshot_location_nonblank",
            "inventory_snapshots",
            "location_code IS NULL OR length(trim(location_code)) > 0",
        )
        op.create_check_constraint(
            "ck_inventory_freshness_backroom_wms_location",
            "inventory_freshness_policies",
            "backroom_location_code IS NULL OR (source = 'WMS' AND length(trim(backroom_location_code)) > 0)",
        )
    elif dialect == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_snapshot_provenance_insert_0084
            BEFORE INSERT ON inventory_snapshots
            BEGIN
                SELECT CASE WHEN NEW.availability_status NOT IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN')
                    THEN RAISE(ABORT, 'invalid inventory snapshot availability status') END;
                SELECT CASE WHEN NEW.location_code IS NOT NULL AND length(trim(NEW.location_code)) = 0
                    THEN RAISE(ABORT, 'inventory snapshot location code cannot be blank') END;
                SELECT CASE WHEN NEW.source = 'WMS' AND (
                    NEW.location_code IS NULL
                    OR length(trim(NEW.location_code)) = 0
                    OR NEW.availability_status NOT IN ('AVAILABLE', 'UNAVAILABLE')
                ) THEN RAISE(ABORT, 'new WMS snapshots require physical location and explicit availability') END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_freshness_backroom_policy_insert_0084
            BEFORE INSERT ON inventory_freshness_policies
            BEGIN
                SELECT CASE WHEN NEW.backroom_location_code IS NOT NULL
                    AND (NEW.source <> 'WMS' OR length(trim(NEW.backroom_location_code)) = 0)
                    THEN RAISE(ABORT, 'backroom location is only valid for WMS and cannot be blank') END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_freshness_backroom_policy_update_0084
            BEFORE UPDATE OF source, backroom_location_code ON inventory_freshness_policies
            BEGIN
                SELECT CASE WHEN NEW.backroom_location_code IS NOT NULL
                    AND (NEW.source <> 'WMS' OR length(trim(NEW.backroom_location_code)) = 0)
                    THEN RAISE(ABORT, 'backroom location is only valid for WMS and cannot be blank') END;
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_snapshot_wms_provenance_0084 ON inventory_snapshots")
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_snapshot_wms_provenance_0084()")
        op.drop_constraint(
            "ck_inventory_freshness_backroom_wms_location",
            "inventory_freshness_policies",
            type_="check",
        )
        op.drop_constraint(
            "ck_inventory_snapshot_location_nonblank",
            "inventory_snapshots",
            type_="check",
        )
        op.drop_constraint(
            "ck_inventory_snapshot_availability_status",
            "inventory_snapshots",
            type_="check",
        )
    elif dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_snapshot_provenance_insert_0084")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_freshness_backroom_policy_insert_0084")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_freshness_backroom_policy_update_0084")

    op.drop_column("inventory_freshness_policies", "backroom_location_code")
    op.drop_index("ix_inventory_snapshot_backroom_lookup", table_name="inventory_snapshots")
    op.drop_column("inventory_snapshots", "availability_status")
    op.drop_column("inventory_snapshots", "location_code")
