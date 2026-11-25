"""Add operational replenishment tasks."""
from alembic import op
import sqlalchemy as sa

revision = "0004_tasks"
down_revision = "0003_inventory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "replenishment_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("priority", sa.String(length=12), nullable=False, server_default="NORMAL"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("assigned_to", sa.String(length=120), nullable=True),
        sa.Column("requested_quantity", sa.Numeric(12, 3), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')", name="ck_task_priority"),
        sa.CheckConstraint("status IN ('PENDING', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')", name="ck_task_status"),
        sa.CheckConstraint("requested_quantity IS NULL OR requested_quantity > 0", name="ck_task_quantity_positive"),
    )
    op.create_index("ix_replenishment_tasks_store_id", "replenishment_tasks", ["store_id"])
    op.create_index("ix_replenishment_tasks_shelf_id", "replenishment_tasks", ["shelf_id"])
    op.create_index("ix_replenishment_tasks_product_id", "replenishment_tasks", ["product_id"])
    op.create_index("ix_replenishment_tasks_status", "replenishment_tasks", ["status"])
    op.create_index("ix_replenishment_tasks_assigned_to", "replenishment_tasks", ["assigned_to"])


def downgrade() -> None:
    op.drop_index("ix_replenishment_tasks_assigned_to", table_name="replenishment_tasks")
    op.drop_index("ix_replenishment_tasks_status", table_name="replenishment_tasks")
    op.drop_index("ix_replenishment_tasks_product_id", table_name="replenishment_tasks")
    op.drop_index("ix_replenishment_tasks_shelf_id", table_name="replenishment_tasks")
    op.drop_index("ix_replenishment_tasks_store_id", table_name="replenishment_tasks")
    op.drop_table("replenishment_tasks")
