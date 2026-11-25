"""Add explicit retention metadata to shelf images.

This migration only introduces lifecycle metadata. It deliberately does not
change image visibility, delete files, or modify historical evidence relations.
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_shelf_image_retention_metadata"
down_revision = "0022_inventory_freshness_policy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shelf_images",
        sa.Column("retention_status", sa.String(length=20), nullable=False, server_default="ACTIVE"),
    )
    op.add_column("shelf_images", sa.Column("retention_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "shelf_images",
        sa.Column(
            "retention_requested_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("shelf_images", sa.Column("retention_reason", sa.Text(), nullable=True))
    op.add_column(
        "shelf_images",
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("shelf_images", sa.Column("purge_not_before", sa.DateTime(timezone=True), nullable=True))
    op.add_column("shelf_images", sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("shelf_images", sa.Column("retention_policy_version", sa.String(length=40), nullable=True))
    op.create_check_constraint(
        "ck_shelf_images_retention_status",
        "shelf_images",
        "retention_status IN ('ACTIVE', 'RESTRICTED', 'PENDING_PURGE', 'PURGED')",
    )
    op.create_index("ix_shelf_images_retention_status", "shelf_images", ["retention_status"])
    op.create_index(
        "ix_shelf_images_retention_requested_by_user_id",
        "shelf_images",
        ["retention_requested_by_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shelf_images_retention_requested_by_user_id", table_name="shelf_images")
    op.drop_index("ix_shelf_images_retention_status", table_name="shelf_images")
    op.drop_constraint("ck_shelf_images_retention_status", "shelf_images", type_="check")
    op.drop_column("shelf_images", "retention_policy_version")
    op.drop_column("shelf_images", "purged_at")
    op.drop_column("shelf_images", "purge_not_before")
    op.drop_column("shelf_images", "legal_hold")
    op.drop_column("shelf_images", "retention_reason")
    op.drop_column("shelf_images", "retention_requested_by_user_id")
    op.drop_column("shelf_images", "retention_requested_at")
    op.drop_column("shelf_images", "retention_status")
