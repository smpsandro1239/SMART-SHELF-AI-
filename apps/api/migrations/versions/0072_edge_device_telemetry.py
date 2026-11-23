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
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
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
    elif bind.dialect.name == "sqlite":
        for action in ("INSERT", "UPDATE"):
            op.execute(f"""
                CREATE TRIGGER trg_edge_device_telemetry_{action.lower()}_0072
                BEFORE {action} ON edge_devices
                WHEN (NEW.last_network_status IS NOT NULL
                      AND NEW.last_network_status NOT IN ('ONLINE', 'DEGRADED', 'OFFLINE'))
                  OR (NEW.battery_pct IS NOT NULL
                      AND (NEW.battery_pct < 0 OR NEW.battery_pct > 100))
                  OR (NEW.storage_free_bytes IS NOT NULL AND NEW.storage_free_bytes < 0)
                BEGIN
                    SELECT RAISE(ABORT, 'edge device telemetry violates health constraints');
                END
            """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint("ck_edge_device_storage_free_bytes", "edge_devices", type_="check")
        op.drop_constraint("ck_edge_device_battery_pct", "edge_devices", type_="check")
        op.drop_constraint("ck_edge_device_network_status", "edge_devices", type_="check")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_edge_device_telemetry_insert_0072")
        op.execute("DROP TRIGGER IF EXISTS trg_edge_device_telemetry_update_0072")
    op.drop_index("ix_edge_devices_last_seen_at", table_name="edge_devices")
    op.drop_column("edge_devices", "storage_free_bytes")
    op.drop_column("edge_devices", "battery_pct")
    op.drop_column("edge_devices", "firmware_version")
    op.drop_column("edge_devices", "last_network_status")
    op.drop_column("edge_devices", "last_seen_at")
