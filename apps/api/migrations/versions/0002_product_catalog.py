"""Add product catalog and shelf assignments."""
from alembic import op
import sqlalchemy as sa

revision = "0002_catalog"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("brand", sa.String(length=120), nullable=True),
        sa.Column("unit", sa.String(length=30), nullable=False, server_default="un"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_products_sku", "products", ["sku"], unique=True)
    op.create_index("ix_products_name", "products", ["name"])

    op.create_table(
        "shelf_products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("min_display_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("position", sa.String(length=80), nullable=True),
        sa.UniqueConstraint("shelf_id", "product_id", name="uq_shelf_products_shelf_product"),
        sa.CheckConstraint("target_quantity > 0", name="ck_shelf_products_target_quantity_positive"),
        sa.CheckConstraint("min_display_quantity >= 0", name="ck_shelf_products_min_display_nonnegative"),
    )
    op.create_index("ix_shelf_products_shelf_id", "shelf_products", ["shelf_id"])
    op.create_index("ix_shelf_products_product_id", "shelf_products", ["product_id"])


def downgrade() -> None:
    op.drop_index("ix_shelf_products_product_id", table_name="shelf_products")
    op.drop_index("ix_shelf_products_shelf_id", table_name="shelf_products")
    op.drop_table("shelf_products")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_table("products")
