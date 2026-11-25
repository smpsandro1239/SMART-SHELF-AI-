"""Add WMS physical-location provenance and per-store backroom authority."""
from alembic import op
import sqlalchemy as sa

revision = "0084_wms_backroom_location_authority"
down_revision = "0083_inventory_sync_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    op.create_index(
        "ix_inventory_snapshot_backroom_lookup",
        "inventory_snapshots",
        ["store_id", "product_id", "source", "location_code", "availability_status", "captured_at"],
    )

    op.add_column(
        "inventory_freshness_policies",
        sa.Column("backroom_location_code", sa.String(length=120), nullable=True),
    )
    op.create_check_constraint(
        "ck_inventory_freshness_backroom_wms_location",
        "inventory_freshness_policies",
        "backroom_location_code IS NULL OR (source = 'WMS' AND length(trim(backroom_location_code)) > 0)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_inventory_freshness_backroom_wms_location",
        "inventory_freshness_policies",
        type_="check",
    )
    op.drop_column("inventory_freshness_policies", "backroom_location_code")
    op.drop_index("ix_inventory_snapshot_backroom_lookup", table_name="inventory_snapshots")
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
    op.drop_column("inventory_snapshots", "availability_status")
    op.drop_column("inventory_snapshots", "location_code")
