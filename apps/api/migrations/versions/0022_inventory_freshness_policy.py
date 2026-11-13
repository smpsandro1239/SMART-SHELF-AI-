"""Add store/source-specific inventory freshness policies."""
from alembic import op
import sqlalchemy as sa

revision = "0022_inventory_freshness_policy"
down_revision = "0021_inventory_reconciliation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_freshness_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("max_age_minutes", sa.Integer(), nullable=False, server_default="240"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("store_id", "source", name="uq_inventory_freshness_store_source"),
        sa.CheckConstraint("source IN ('ERP', 'WMS', 'POS', 'MANUAL', 'IMPORT')", name="ck_inventory_freshness_source"),
        sa.CheckConstraint("max_age_minutes >= 1 AND max_age_minutes <= 10080", name="ck_inventory_freshness_max_age"),
    )
    op.create_index("ix_inventory_freshness_policies_store_id", "inventory_freshness_policies", ["store_id"])


def downgrade() -> None:
    op.drop_index("ix_inventory_freshness_policies_store_id", table_name="inventory_freshness_policies")
    op.drop_table("inventory_freshness_policies")
