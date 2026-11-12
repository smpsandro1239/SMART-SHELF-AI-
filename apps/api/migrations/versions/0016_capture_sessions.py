"""Add operational capture sessions and link shelf images to sessions."""
from alembic import op
import sqlalchemy as sa

revision = "0016_capture_sessions"
down_revision = "0015_shelf_image_ocr_matches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capture_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_device_id", sa.String(length=120), nullable=True),
        sa.Column("capture_mode", sa.String(length=20), nullable=False, server_default="single"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("source_type IN ('fixed_camera', 'robot', 'mobile')", name="ck_capture_session_source"),
        sa.CheckConstraint("capture_mode IN ('single', 'burst', 'video_sample')", name="ck_capture_session_mode"),
        sa.CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_capture_session_time_range"),
    )
    op.create_index("ix_capture_sessions_store_id", "capture_sessions", ["store_id"])
    op.create_index("ix_capture_sessions_shelf_id", "capture_sessions", ["shelf_id"])
    op.create_index("ix_capture_sessions_source_device_id", "capture_sessions", ["source_device_id"])
    op.add_column("shelf_images", sa.Column("capture_session_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_shelf_images_capture_session_id_capture_sessions", "shelf_images", "capture_sessions", ["capture_session_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_shelf_images_capture_session_id", "shelf_images", ["capture_session_id"])


def downgrade() -> None:
    op.drop_index("ix_shelf_images_capture_session_id", table_name="shelf_images")
    op.drop_constraint("fk_shelf_images_capture_session_id_capture_sessions", "shelf_images", type_="foreignkey")
    op.drop_column("shelf_images", "capture_session_id")
    op.drop_index("ix_capture_sessions_source_device_id", table_name="capture_sessions")
    op.drop_index("ix_capture_sessions_shelf_id", table_name="capture_sessions")
    op.drop_index("ix_capture_sessions_store_id", table_name="capture_sessions")
    op.drop_table("capture_sessions")
