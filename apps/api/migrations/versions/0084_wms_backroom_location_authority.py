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
    with op.batch_alter_table("inventory_snapshots") as batch_op:
        batch_op.create_check_constraint(
            "ck_inventory_snapshot_availability_status",
            "availability_status IN ('AVAILABLE', 'UNAVAILABLE', 'UNKNOWN')",
        )
        batch_op.create_check_constraint(
            "ck_inventory_snapshot_location_nonblank",
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
    with op.batch_alter_table("inventory_freshness_policies") as batch_op:
        batch_op.create_check_constraint(
            "ck_inventory_freshness_backroom_wms_location",
            "backroom_location_code IS NULL OR (source = 'WMS' AND length(trim(backroom_location_code)) > 0)",
        )


def downgrade() -> None:
    with op.batch_alter_table("inventory_freshness_policies") as batch_op:
        batch_op.drop_constraint(
            "ck_inventory_freshness_backroom_wms_location",
            type_="check",
        )
        batch_op.drop_column("backroom_location_code")
    op.drop_index("ix_inventory_snapshot_backroom_lookup", table_name="inventory_snapshots")
    with op.batch_alter_table("inventory_snapshots") as batch_op:
        batch_op.drop_constraint("ck_inventory_snapshot_location_nonblank", type_="check")
        batch_op.drop_constraint("ck_inventory_snapshot_availability_status", type_="check")
        batch_op.drop_column("availability_status")
        batch_op.drop_column("location_code")
