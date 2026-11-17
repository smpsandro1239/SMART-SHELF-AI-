"""Add physical pallet identities, rotation policies and lifecycle audit events."""

from alembic import op
import sqlalchemy as sa

revision = "0015_pallet_rotation_registry"
down_revision = "0014_product_packaging_levels"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "store_pallets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("packaging_level_id", sa.Integer(), sa.ForeignKey("product_packaging_levels.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("pallet_code", sa.String(length=100), nullable=False),
        sa.Column("lot_code", sa.String(length=100), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("base_quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="READY", nullable=False),
        sa.Column("location_type", sa.String(length=16), server_default="WAREHOUSE", nullable=False),
        sa.Column("location_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("store_id", "pallet_code", name="uq_store_pallet_store_code"),
        sa.CheckConstraint("base_quantity >= 0", name="ck_store_pallet_quantity_nonnegative"),
        sa.CheckConstraint("(status = 'EMPTY' AND base_quantity = 0) OR (status <> 'EMPTY' AND base_quantity > 0)", name="ck_store_pallet_status_quantity"),
        sa.CheckConstraint("status IN ('READY', 'ON_DISPLAY', 'PARTIAL', 'RETURNED', 'REBUILDING', 'EMPTY', 'QUARANTINED')", name="ck_store_pallet_status"),
        sa.CheckConstraint("location_type IN ('WAREHOUSE', 'PREPARATION', 'SALES_FLOOR', 'OTHER')", name="ck_store_pallet_location_type"),
    )
    op.create_index("ix_store_pallets_store_id", "store_pallets", ["store_id"])
    op.create_index("ix_store_pallets_product_id", "store_pallets", ["product_id"])
    op.create_index("ix_store_pallets_packaging_level_id", "store_pallets", ["packaging_level_id"])
    op.create_index("ix_store_pallets_lot_code", "store_pallets", ["lot_code"])
    op.create_index("ix_store_pallets_expiry_date", "store_pallets", ["expiry_date"])
    op.create_index("ix_store_pallets_status", "store_pallets", ["status"])

    op.create_table(
        "pallet_rotation_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("threshold_ratio", sa.Numeric(5, 4), server_default="0.5", nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("store_id", "product_id", name="uq_pallet_rotation_policy_store_product"),
        sa.CheckConstraint("threshold_ratio > 0 AND threshold_ratio <= 1", name="ck_pallet_rotation_threshold_range"),
    )
    op.create_index("ix_pallet_rotation_policies_store_id", "pallet_rotation_policies", ["store_id"])
    op.create_index("ix_pallet_rotation_policies_product_id", "pallet_rotation_policies", ["product_id"])

    op.create_table(
        "pallet_rotation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pallet_id", sa.Integer(), sa.ForeignKey("store_pallets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("from_location_type", sa.String(length=16), nullable=True),
        sa.Column("from_location_code", sa.String(length=100), nullable=True),
        sa.Column("to_location_type", sa.String(length=16), nullable=True),
        sa.Column("to_location_code", sa.String(length=100), nullable=True),
        sa.Column("quantity_before", sa.Numeric(14, 3), nullable=False),
        sa.Column("quantity_after", sa.Numeric(14, 3), nullable=False),
        sa.Column("lot_code", sa.String(length=100), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("performed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('REGISTERED', 'STATUS_REVIEWED', 'LOCATION_RECORDED', 'QUANTITY_RECORDED', 'LOT_REVIEWED', 'EXCEPTION_RECORDED')", name="ck_pallet_event_type"),
        sa.CheckConstraint("quantity_before >= 0 AND quantity_after >= 0", name="ck_pallet_event_quantities_nonnegative"),
    )
    op.create_index("ix_pallet_rotation_events_pallet_id", "pallet_rotation_events", ["pallet_id"])
    op.create_index("ix_pallet_rotation_events_performed_by_user_id", "pallet_rotation_events", ["performed_by_user_id"])
    op.create_index("ix_pallet_rotation_events_occurred_at", "pallet_rotation_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_pallet_rotation_events_occurred_at", table_name="pallet_rotation_events")
    op.drop_index("ix_pallet_rotation_events_performed_by_user_id", table_name="pallet_rotation_events")
    op.drop_index("ix_pallet_rotation_events_pallet_id", table_name="pallet_rotation_events")
    op.drop_table("pallet_rotation_events")
    op.drop_index("ix_pallet_rotation_policies_product_id", table_name="pallet_rotation_policies")
    op.drop_index("ix_pallet_rotation_policies_store_id", table_name="pallet_rotation_policies")
    op.drop_table("pallet_rotation_policies")
    op.drop_index("ix_store_pallets_status", table_name="store_pallets")
    op.drop_index("ix_store_pallets_expiry_date", table_name="store_pallets")
    op.drop_index("ix_store_pallets_lot_code", table_name="store_pallets")
    op.drop_index("ix_store_pallets_packaging_level_id", table_name="store_pallets")
    op.drop_index("ix_store_pallets_product_id", table_name="store_pallets")
    op.drop_index("ix_store_pallets_store_id", table_name="store_pallets")
    op.drop_table("store_pallets")
