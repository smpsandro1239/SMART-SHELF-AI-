"""Add last-seen and health telemetry to registered Edge devices."""

from alembic import op
import sqlalchemy as sa


revision = "0072_edge_device_telemetry"
down_revision = "0071_edge_device_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("edge_devices", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("edge_devices", sa.Column("last_network_status", sa.String(length=12), nullable=True))
    op.add_column("edge_devices", sa.Column("firmware_version", sa.String(length=100), nullable=True))
    op.add_column("edge_devices", sa.Column("battery_pct", sa.Float(), nullable=True))
    op.add_column("edge_devices", sa.Column("storage_free_bytes", sa.BigInteger(), nullable=True))
    op.create_index("ix_edge_devices_last_seen_at", "edge_devices", ["last_seen_at"])
    op.create_check_constraint(
        "ck_edge_device_network_status", "edge_devices",
        "last_network_status IS NULL OR last_network_status IN ('ONLINE', 'DEGRADED', 'OFFLINE')",
    )
    op.create_check_constraint(
        "ck_edge_device_battery_pct", "edge_devices",
        "battery_pct IS NULL OR (battery_pct >= 0 AND battery_pct <= 100)",
    )
    op.create_check_constraint(
        "ck_edge_device_storage_free_bytes", "edge_devices",
        "storage_free_bytes IS NULL OR storage_free_bytes >= 0",
    )


def downgrade() -> None:
    with op.batch_alter_table("edge_devices") as batch_op:
        batch_op.drop_constraint("ck_edge_device_storage_free_bytes", type_="check")
        batch_op.drop_constraint("ck_edge_device_battery_pct", type_="check")
        batch_op.drop_constraint("ck_edge_device_network_status", type_="check")
        batch_op.drop_index("ix_edge_devices_last_seen_at")
        batch_op.drop_column("storage_free_bytes")
        batch_op.drop_column("battery_pct")
        batch_op.drop_column("firmware_version")
        batch_op.drop_column("last_network_status")
        batch_op.drop_column("last_seen_at")
