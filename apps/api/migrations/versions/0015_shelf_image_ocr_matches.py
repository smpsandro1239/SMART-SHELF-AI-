"""Persist explainable OCR-to-catalogue matching results."""
from alembic import op
import sqlalchemy as sa

revision = "0015_shelf_image_ocr_matches"
down_revision = "0014_shelf_image_ocr_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelf_image_ocr_matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("shelf_image_ocr_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("detection_id", sa.Integer(), sa.ForeignKey("shelf_image_detections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("suggested_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("observed_text", sa.Text(), nullable=False),
        sa.Column("ocr_confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("top_score", sa.Float(), nullable=True),
        sa.Column("margin", sa.Float(), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "detection_id", name="uq_ocr_match_run_detection"),
        sa.CheckConstraint("status IN ('SUGGESTED', 'AMBIGUOUS', 'UNKNOWN')", name="ck_ocr_match_status"),
        sa.CheckConstraint("top_score IS NULL OR (top_score >= 0 AND top_score <= 1)", name="ck_ocr_match_score"),
        sa.CheckConstraint("ocr_confidence >= 0 AND ocr_confidence <= 1", name="ck_ocr_match_confidence"),
    )
    op.create_index("ix_shelf_image_ocr_matches_run_id", "shelf_image_ocr_matches", ["run_id"])
    op.create_index("ix_shelf_image_ocr_matches_detection_id", "shelf_image_ocr_matches", ["detection_id"])
    op.create_index("ix_shelf_image_ocr_matches_suggested_product_id", "shelf_image_ocr_matches", ["suggested_product_id"])
    op.create_index("ix_shelf_image_ocr_matches_status", "shelf_image_ocr_matches", ["status"])


def downgrade() -> None:
    op.drop_index("ix_shelf_image_ocr_matches_status", table_name="shelf_image_ocr_matches")
    op.drop_index("ix_shelf_image_ocr_matches_suggested_product_id", table_name="shelf_image_ocr_matches")
    op.drop_index("ix_shelf_image_ocr_matches_detection_id", table_name="shelf_image_ocr_matches")
    op.drop_index("ix_shelf_image_ocr_matches_run_id", table_name="shelf_image_ocr_matches")
    op.drop_table("shelf_image_ocr_matches")
