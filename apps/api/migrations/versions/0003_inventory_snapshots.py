"""Add append-only inventory snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0003_inventory"
down_revision = "0002_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("on_hand_quantity", sa.Numeric(12, 3), nullable=False),
        sa.Column("reserved_quantity", sa.Numeric(12, 3), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("external_reference", sa.String(length=120), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("on_hand_quantity >= 0", name="ck_inventory_on_hand_nonnegative"),
        sa.CheckConstraint("reserved_quantity >= 0", name="ck_inventory_reserved_nonnegative"),
        sa.CheckConstraint("reserved_quantity <= on_hand_quantity", name="ck_inventory_reserved_lte_on_hand"),
        sa.UniqueConstraint("store_id", "product_id", "source", "external_reference",
                            name="uq_inventory_snapshot_source_reference"),
    )
    op.create_index("ix_inventory_snapshots_store_id", "inventory_snapshots", ["store_id"])
    op.create_index("ix_inventory_snapshots_product_id", "inventory_snapshots", ["product_id"])
    op.create_index("ix_inventory_snapshots_captured_at", "inventory_snapshots", ["captured_at"])


def downgrade() -> None:
    op.drop_index("ix_inventory_snapshots_captured_at", table_name="inventory_snapshots")
    op.drop_index("ix_inventory_snapshots_product_id", table_name="inventory_snapshots")
    op.drop_index("ix_inventory_snapshots_store_id", table_name="inventory_snapshots")
    op.drop_table("inventory_snapshots")
