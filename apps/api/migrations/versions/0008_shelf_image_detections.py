"""Persist computer-vision detections for shelf images."""
from alembic import op
import sqlalchemy as sa

revision = "0008_shelf_image_detections"
down_revision = "0007_shelf_images"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelf_image_detections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shelf_image_id", sa.Integer(), sa.ForeignKey("shelf_images.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("x_min", sa.Float(), nullable=False),
        sa.Column("y_min", sa.Float(), nullable=False),
        sa.Column("x_max", sa.Float(), nullable=False),
        sa.Column("y_max", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_detection_confidence_range"),
        sa.CheckConstraint("x_min >= 0 AND x_min <= 1 AND y_min >= 0 AND y_min <= 1", name="ck_detection_bbox_min_range"),
        sa.CheckConstraint("x_max >= 0 AND x_max <= 1 AND y_max >= 0 AND y_max <= 1", name="ck_detection_bbox_max_range"),
        sa.CheckConstraint("x_min < x_max AND y_min < y_max", name="ck_detection_bbox_order"),
    )
    op.create_index("ix_shelf_image_detections_shelf_image_id", "shelf_image_detections", ["shelf_image_id"])
    op.create_index("ix_shelf_image_detections_product_id", "shelf_image_detections", ["product_id"])
    op.create_index("ix_shelf_image_detections_label", "shelf_image_detections", ["label"])


def downgrade() -> None:
    op.drop_index("ix_shelf_image_detections_label", table_name="shelf_image_detections")
    op.drop_index("ix_shelf_image_detections_product_id", table_name="shelf_image_detections")
    op.drop_index("ix_shelf_image_detections_shelf_image_id", table_name="shelf_image_detections")
    op.drop_table("shelf_image_detections")
