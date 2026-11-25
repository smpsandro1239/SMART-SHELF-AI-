"""Add store-scoped external integration registry."""
from alembic import op
import sqlalchemy as sa

revision = "0036_store_external_integrations"
down_revision = "0035_shelf_image_artifact_inventory_snapshots"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "store_external_integrations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_system", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="ACTIVE"),
        sa.Column("required_for_retention", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("updated_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("store_id", "external_system", name="uq_store_external_integration_system"),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_store_external_integration_status"),
    )
    op.create_index(
        "ix_store_external_integrations_store_status",
        "store_external_integrations",
        ["store_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_store_external_integrations_store_status", table_name="store_external_integrations")
    op.drop_table("store_external_integrations")
