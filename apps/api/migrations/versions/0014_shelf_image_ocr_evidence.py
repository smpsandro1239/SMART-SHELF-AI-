"""Persist OCR inference runs and per-region evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0014_shelf_image_ocr_evidence"
down_revision = "0013_detection_sku_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelf_image_ocr_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shelf_image_id", sa.Integer(), sa.ForeignKey("shelf_images.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_version", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="COMPLETED"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('COMPLETED', 'FAILED')", name="ck_shelf_image_ocr_run_status"),
    )
    op.create_index("ix_shelf_image_ocr_runs_shelf_image_id", "shelf_image_ocr_runs", ["shelf_image_id"])

    op.create_table(
        "shelf_image_ocr_evidence",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("shelf_image_ocr_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("detection_id", sa.Integer(), sa.ForeignKey("shelf_image_detections.id", ondelete="SET NULL"), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.String(length=1000), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("x_min", sa.Float(), nullable=False),
        sa.Column("y_min", sa.Float(), nullable=False),
        sa.Column("x_max", sa.Float(), nullable=False),
        sa.Column("y_max", sa.Float(), nullable=False),
        sa.Column("association_status", sa.String(length=12), nullable=False, server_default="UNASSIGNED"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_shelf_ocr_confidence_range"),
        sa.CheckConstraint("x_min >= 0 AND x_min <= 1 AND y_min >= 0 AND y_min <= 1", name="ck_shelf_ocr_bbox_min_range"),
        sa.CheckConstraint("x_max >= 0 AND x_max <= 1 AND y_max >= 0 AND y_max <= 1", name="ck_shelf_ocr_bbox_max_range"),
        sa.CheckConstraint("x_min < x_max AND y_min < y_max", name="ck_shelf_ocr_bbox_order"),
        sa.CheckConstraint("association_status IN ('ASSIGNED', 'UNASSIGNED')", name="ck_shelf_ocr_association_status"),
    )
    op.create_index("ix_shelf_image_ocr_evidence_run_id", "shelf_image_ocr_evidence", ["run_id"])
    op.create_index("ix_shelf_image_ocr_evidence_detection_id", "shelf_image_ocr_evidence", ["detection_id"])


def downgrade() -> None:
    op.drop_index("ix_shelf_image_ocr_evidence_detection_id", table_name="shelf_image_ocr_evidence")
    op.drop_index("ix_shelf_image_ocr_evidence_run_id", table_name="shelf_image_ocr_evidence")
    op.drop_table("shelf_image_ocr_evidence")
    op.drop_index("ix_shelf_image_ocr_runs_shelf_image_id", table_name="shelf_image_ocr_runs")
    op.drop_table("shelf_image_ocr_runs")
