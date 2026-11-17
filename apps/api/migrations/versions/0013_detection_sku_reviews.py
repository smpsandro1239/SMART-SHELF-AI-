"""Add append-only human SKU review history for detections."""
from alembic import op
import sqlalchemy as sa

revision = "0013_detection_sku_reviews"
down_revision = "0012_detection_sku_matching"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "detection_sku_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("detection_id", sa.Integer(), sa.ForeignKey("shelf_image_detections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("previous_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("selected_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("decision", sa.String(length=12), nullable=False),
        sa.Column("reviewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("decision IN ('CONFIRMED', 'CORRECTED', 'REJECTED')", name="ck_detection_sku_review_decision"),
        sa.CheckConstraint("(decision = 'REJECTED' AND selected_product_id IS NULL) OR (decision IN ('CONFIRMED', 'CORRECTED') AND selected_product_id IS NOT NULL)", name="ck_detection_sku_review_selected_product"),
    )
    op.create_index("ix_detection_sku_reviews_detection_id", "detection_sku_reviews", ["detection_id"])
    op.create_index("ix_detection_sku_reviews_selected_product_id", "detection_sku_reviews", ["selected_product_id"])
    op.create_index("ix_detection_sku_reviews_decision", "detection_sku_reviews", ["decision"])
    op.create_index("ix_detection_sku_reviews_reviewer_user_id", "detection_sku_reviews", ["reviewer_user_id"])


def downgrade() -> None:
    op.drop_index("ix_detection_sku_reviews_reviewer_user_id", table_name="detection_sku_reviews")
    op.drop_index("ix_detection_sku_reviews_decision", table_name="detection_sku_reviews")
    op.drop_index("ix_detection_sku_reviews_selected_product_id", table_name="detection_sku_reviews")
    op.drop_index("ix_detection_sku_reviews_detection_id", table_name="detection_sku_reviews")
    op.drop_table("detection_sku_reviews")
