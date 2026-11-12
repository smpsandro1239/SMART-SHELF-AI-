"""Add physical warehouse locations and product placement constraints."""

from alembic import op
import sqlalchemy as sa

revision = "0013_warehouse_slotting_locations"
down_revision = "0012_detection_sku_matching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warehouse_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("aisle", sa.String(length=40), nullable=True),
        sa.Column("rack", sa.String(length=40), nullable=True),
        sa.Column("bin_code", sa.String(length=40), nullable=True),
        sa.Column("distance_to_picking_m", sa.Numeric(10, 2), nullable=False),
        sa.Column("max_volume_cm3", sa.Numeric(14, 2), nullable=False),
        sa.Column("max_weight_kg", sa.Numeric(12, 3), nullable=False),
        sa.Column("temperature_zone", sa.String(length=12), server_default="AMBIENT", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("store_id", "code", name="uq_warehouse_location_store_code"),
        sa.CheckConstraint("distance_to_picking_m >= 0", name="ck_warehouse_location_distance_nonnegative"),
        sa.CheckConstraint("max_volume_cm3 > 0", name="ck_warehouse_location_volume_positive"),
        sa.CheckConstraint("max_weight_kg > 0", name="ck_warehouse_location_weight_positive"),
        sa.CheckConstraint("temperature_zone IN ('AMBIENT', 'CHILLED', 'FROZEN')", name="ck_warehouse_location_temperature"),
    )
    op.create_index("ix_warehouse_locations_store_id", "warehouse_locations", ["store_id"])

    op.create_table(
        "warehouse_product_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("unit_volume_cm3", sa.Numeric(12, 2), nullable=False),
        sa.Column("unit_weight_kg", sa.Numeric(10, 3), nullable=False),
        sa.Column("temperature_requirement", sa.String(length=12), server_default="AMBIENT", nullable=False),
        sa.Column("is_fragile", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("requires_segregation", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.UniqueConstraint("product_id", name="uq_warehouse_product_profile_product"),
        sa.CheckConstraint("unit_volume_cm3 > 0", name="ck_warehouse_product_volume_positive"),
        sa.CheckConstraint("unit_weight_kg > 0", name="ck_warehouse_product_weight_positive"),
        sa.CheckConstraint("temperature_requirement IN ('AMBIENT', 'CHILLED', 'FROZEN')", name="ck_warehouse_product_temperature"),
    )
    op.create_index("ix_warehouse_product_profiles_product_id", "warehouse_product_profiles", ["product_id"])

    op.create_table(
        "warehouse_product_placements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("location_id", sa.Integer(), sa.ForeignKey("warehouse_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("location_id", "product_id", name="uq_warehouse_placement_location_product"),
        sa.CheckConstraint("quantity >= 0", name="ck_warehouse_placement_quantity_nonnegative"),
    )
    op.create_index("ix_warehouse_product_placements_location_id", "warehouse_product_placements", ["location_id"])
    op.create_index("ix_warehouse_product_placements_product_id", "warehouse_product_placements", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_warehouse_product_placements_product_id", table_name="warehouse_product_placements")
    op.drop_index("ix_warehouse_product_placements_location_id", table_name="warehouse_product_placements")
    op.drop_table("warehouse_product_placements")
    op.drop_index("ix_warehouse_product_profiles_product_id", table_name="warehouse_product_profiles")
    op.drop_table("warehouse_product_profiles")
    op.drop_index("ix_warehouse_locations_store_id", table_name="warehouse_locations")
    op.drop_table("warehouse_locations")
