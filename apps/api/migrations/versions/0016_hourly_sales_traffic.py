"""Add store-local hourly sales and traffic observations."""
from alembic import op
import sqlalchemy as sa

revision = "0016_hourly_sales_traffic"
down_revision = "0015_pallet_rotation_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hourly_sales_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("hour_of_day", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_reference", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("store_id", "product_id", "business_date", "hour_of_day", "source", "external_reference", name="uq_hourly_sales_external_reference"),
        sa.CheckConstraint("quantity >= 0", name="ck_hourly_sales_quantity_nonnegative"),
        sa.CheckConstraint("hour_of_day >= 0 AND hour_of_day <= 23", name="ck_hourly_sales_hour_range"),
        sa.CheckConstraint("source IN ('POS', 'ERP', 'MANUAL', 'IMPORT')", name="ck_hourly_sales_source"),
    )
    for column in ("store_id", "product_id", "business_date", "hour_of_day"):
        op.create_index(f"ix_hourly_sales_records_{column}", "hourly_sales_records", [column])
    op.create_index("ix_hourly_sales_store_product_date_hour", "hourly_sales_records",
                    ["store_id", "product_id", "business_date", "hour_of_day"])

    op.create_table(
        "hourly_store_traffic_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("hour_of_day", sa.Integer(), nullable=False),
        sa.Column("customer_count", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("external_reference", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("store_id", "business_date", "hour_of_day", "source", "external_reference", name="uq_hourly_traffic_external_reference"),
        sa.CheckConstraint("customer_count >= 0", name="ck_hourly_traffic_count_nonnegative"),
        sa.CheckConstraint("hour_of_day >= 0 AND hour_of_day <= 23", name="ck_hourly_traffic_hour_range"),
        sa.CheckConstraint("source IN ('POS', 'ERP', 'MANUAL', 'IMPORT')", name="ck_hourly_traffic_source"),
    )
    for column in ("store_id", "business_date", "hour_of_day"):
        op.create_index(f"ix_hourly_store_traffic_records_{column}", "hourly_store_traffic_records", [column])
    op.create_index("ix_hourly_traffic_store_date_hour", "hourly_store_traffic_records",
                    ["store_id", "business_date", "hour_of_day"])


def downgrade() -> None:
    op.drop_index("ix_hourly_traffic_store_date_hour", table_name="hourly_store_traffic_records")
    for column in ("hour_of_day", "business_date", "store_id"):
        op.drop_index(f"ix_hourly_store_traffic_records_{column}", table_name="hourly_store_traffic_records")
    op.drop_table("hourly_store_traffic_records")
    op.drop_index("ix_hourly_sales_store_product_date_hour", table_name="hourly_sales_records")
    for column in ("hour_of_day", "business_date", "product_id", "store_id"):
        op.drop_index(f"ix_hourly_sales_records_{column}", table_name="hourly_sales_records")
    op.drop_table("hourly_sales_records")
