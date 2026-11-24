"""Add explicit store-scoped ERP/WMS product identity mappings."""
from alembic import op
import sqlalchemy as sa

revision = "0078_inventory_external_product_mapping"
down_revision = "0077_inventory_source_sync_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_external_product_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source", sa.String(8), nullable=False),
        sa.Column("external_product_id", sa.String(120), nullable=False),
        sa.Column("external_sku", sa.String(120), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("store_id", "source", "external_product_id", name="uq_inventory_external_mapping_external_id"),
        sa.UniqueConstraint("store_id", "source", "external_sku", name="uq_inventory_external_mapping_sku"),
        sa.UniqueConstraint("store_id", "source", "product_id", name="uq_inventory_external_mapping_product"),
        sa.CheckConstraint("source IN ('ERP', 'WMS')", name="ck_inventory_external_mapping_source"),
    )
    op.create_index("ix_inventory_external_mapping_product", "inventory_external_product_mappings", ["store_id", "product_id"])


def downgrade() -> None:
    op.drop_index("ix_inventory_external_mapping_product", table_name="inventory_external_product_mappings")
    op.drop_table("inventory_external_product_mappings")
