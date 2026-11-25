"""Persist conservative visual/OCR fusion results."""
from alembic import op
import sqlalchemy as sa

revision = "0016_shelf_image_fused_evidence"
down_revision = "0015_shelf_image_ocr_matches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelf_image_fused_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ocr_run_id", sa.Integer(), sa.ForeignKey("shelf_image_ocr_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("detection_id", sa.Integer(), sa.ForeignKey("shelf_image_detections.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("suggested_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("visual_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("text_product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("visual_status", sa.String(length=12), nullable=False),
        sa.Column("text_status", sa.String(length=12), nullable=False),
        sa.Column("visual_similarity", sa.Float(), nullable=True),
        sa.Column("text_score", sa.Float(), nullable=True),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("visual_model_version", sa.String(length=100), nullable=True),
        sa.Column("ocr_provider", sa.String(length=80), nullable=False),
        sa.Column("ocr_model_version", sa.String(length=120), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("ocr_run_id", "detection_id", name="uq_fused_evidence_run_detection"),
        sa.CheckConstraint("status IN ('CONSENSUS', 'VISUAL_ONLY', 'TEXT_ONLY', 'CONFLICT', 'AMBIGUOUS', 'UNKNOWN')", name="ck_fused_evidence_status"),
        sa.CheckConstraint("ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)", name="ck_fused_evidence_ocr_confidence"),
    )
    op.create_index("ix_shelf_image_fused_evidence_ocr_run_id", "shelf_image_fused_evidence", ["ocr_run_id"])
    op.create_index("ix_shelf_image_fused_evidence_detection_id", "shelf_image_fused_evidence", ["detection_id"])
    op.create_index("ix_shelf_image_fused_evidence_status", "shelf_image_fused_evidence", ["status"])
    op.create_index("ix_shelf_image_fused_evidence_suggested_product_id", "shelf_image_fused_evidence", ["suggested_product_id"])


def downgrade() -> None:
    op.drop_index("ix_shelf_image_fused_evidence_suggested_product_id", table_name="shelf_image_fused_evidence")
    op.drop_index("ix_shelf_image_fused_evidence_status", table_name="shelf_image_fused_evidence")
    op.drop_index("ix_shelf_image_fused_evidence_detection_id", table_name="shelf_image_fused_evidence")
    op.drop_index("ix_shelf_image_fused_evidence_ocr_run_id", table_name="shelf_image_fused_evidence")
    op.drop_table("shelf_image_fused_evidence")
