"""Store immutable daily sales aggregates for demand forecasting."""
from alembic import op
import sqlalchemy as sa

revision = "0017_daily_sales_records"
down_revision = "0016_shelf_image_fused_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_sales_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sales_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_reference", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "store_id", "product_id", "sales_date", "source", "external_reference",
            name="uq_daily_sales_external_reference",
        ),
        sa.CheckConstraint("quantity >= 0", name="ck_daily_sales_quantity_nonnegative"),
        sa.CheckConstraint("source IN ('POS', 'ERP', 'MANUAL', 'IMPORT')", name="ck_daily_sales_source"),
    )
    op.create_index("ix_daily_sales_records_store_id", "daily_sales_records", ["store_id"])
    op.create_index("ix_daily_sales_records_product_id", "daily_sales_records", ["product_id"])
    op.create_index("ix_daily_sales_records_sales_date", "daily_sales_records", ["sales_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_sales_records_sales_date", table_name="daily_sales_records")
    op.drop_index("ix_daily_sales_records_product_id", table_name="daily_sales_records")
    op.drop_index("ix_daily_sales_records_store_id", table_name="daily_sales_records")
    op.drop_table("daily_sales_records")
