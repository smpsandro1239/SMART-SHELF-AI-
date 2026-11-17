"""Add lifecycle metadata to shelf image analysis."""
from alembic import op
import sqlalchemy as sa

revision = "0009_shelf_image_analysis_lifecycle"
down_revision = "0008_shelf_image_detections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shelf_images", sa.Column("analysis_error", sa.Text(), nullable=True))
    op.add_column("shelf_images", sa.Column("analysis_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("shelf_images", sa.Column("analysis_completed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("shelf_images", "analysis_completed_at")
    op.drop_column("shelf_images", "analysis_started_at")
    op.drop_column("shelf_images", "analysis_error")
