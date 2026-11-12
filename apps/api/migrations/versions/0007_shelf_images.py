"""Persist uploaded shelf photographs for the computer-vision pipeline."""
from alembic import op
import sqlalchemy as sa

revision = "0007_shelf_images"
down_revision = "0006_user_store_task_assignee"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelf_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=600), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(length=40), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("analysis_status", sa.String(length=20), nullable=False, server_default="PENDING"),
        sa.Column("model_version", sa.String(length=100), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_shelf_images_shelf_id", "shelf_images", ["shelf_id"])
    op.create_index("ix_shelf_images_uploaded_by", "shelf_images", ["uploaded_by"])
    op.create_index("ix_shelf_images_sha256", "shelf_images", ["sha256"])
    op.create_index("ix_shelf_images_analysis_status", "shelf_images", ["analysis_status"])
    op.create_index("ix_shelf_images_captured_at", "shelf_images", ["captured_at"])


def downgrade() -> None:
    op.drop_index("ix_shelf_images_captured_at", table_name="shelf_images")
    op.drop_index("ix_shelf_images_analysis_status", table_name="shelf_images")
    op.drop_index("ix_shelf_images_sha256", table_name="shelf_images")
    op.drop_index("ix_shelf_images_uploaded_by", table_name="shelf_images")
    op.drop_index("ix_shelf_images_shelf_id", table_name="shelf_images")
    op.drop_table("shelf_images")
