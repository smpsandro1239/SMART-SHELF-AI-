"""Add product packaging and logistics units."""

from alembic import op
import sqlalchemy as sa

revision = "0014_product_packaging_levels"
down_revision = "0013_warehouse_slotting_locations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_packaging_levels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("package_type", sa.String(length=12), nullable=False),
        sa.Column("base_units_per_package", sa.Numeric(14, 3), nullable=False),
        sa.Column("barcode", sa.String(length=80), nullable=True),
        sa.Column("gross_weight_kg", sa.Numeric(12, 3), nullable=True),
        sa.Column("package_volume_cm3", sa.Numeric(14, 2), nullable=True),
        sa.Column("is_ordering_unit", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_replenishment_unit", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.UniqueConstraint("product_id", "code", name="uq_product_packaging_product_code"),
        sa.CheckConstraint("base_units_per_package > 0", name="ck_packaging_base_units_positive"),
        sa.CheckConstraint("package_type IN ('UNIT', 'CASE', 'PALLET', 'OTHER')", name="ck_packaging_type"),
        sa.CheckConstraint("gross_weight_kg IS NULL OR gross_weight_kg > 0", name="ck_packaging_weight_positive"),
        sa.CheckConstraint("package_volume_cm3 IS NULL OR package_volume_cm3 > 0", name="ck_packaging_volume_positive"),
    )
    op.create_index("ix_product_packaging_levels_product_id", "product_packaging_levels", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_product_packaging_levels_product_id", table_name="product_packaging_levels")
    op.drop_table("product_packaging_levels")
