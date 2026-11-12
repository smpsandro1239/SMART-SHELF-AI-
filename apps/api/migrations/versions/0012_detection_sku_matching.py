"""Persist conservative SKU matching results for detections."""
from alembic import op
import sqlalchemy as sa

revision = "0012_detection_sku_matching"
down_revision = "0011_product_embedding_exemplars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shelf_image_detections", sa.Column("embedding_model_version", sa.String(length=100), nullable=True))
    op.add_column("shelf_image_detections", sa.Column("sku_match_status", sa.String(length=12), nullable=False, server_default="UNKNOWN"))
    op.add_column("shelf_image_detections", sa.Column("sku_similarity", sa.Float(), nullable=True))
    op.add_column("shelf_image_detections", sa.Column("sku_match_margin", sa.Float(), nullable=True))
    op.create_check_constraint("ck_detection_sku_match_status", "shelf_image_detections", "sku_match_status IN ('MATCHED', 'AMBIGUOUS', 'UNKNOWN')")


def downgrade() -> None:
    op.drop_constraint("ck_detection_sku_match_status", "shelf_image_detections", type_="check")
    op.drop_column("shelf_image_detections", "sku_match_margin")
    op.drop_column("shelf_image_detections", "sku_similarity")
    op.drop_column("shelf_image_detections", "sku_match_status")
    op.drop_column("shelf_image_detections", "embedding_model_version")
