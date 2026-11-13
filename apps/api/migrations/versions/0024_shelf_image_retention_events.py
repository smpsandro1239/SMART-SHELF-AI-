"""Add append-only audit events for shelf-image retention transitions."""
from alembic import op
import sqlalchemy as sa

revision = "0024_shelf_image_retention_events"
down_revision = "0023_shelf_image_retention_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelf_image_retention_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shelf_image_id", sa.Integer(), sa.ForeignKey("shelf_images.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=False),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('RESTRICTED', 'RESTORED')", name="ck_shelf_image_retention_event_type"),
    )
    op.create_index("ix_shelf_image_retention_events_shelf_image_id", "shelf_image_retention_events", ["shelf_image_id"])
    op.create_index("ix_shelf_image_retention_events_actor_user_id", "shelf_image_retention_events", ["actor_user_id"])
    op.create_index("ix_shelf_image_retention_events_created_at", "shelf_image_retention_events", ["created_at"])
    op.create_index("ix_shelf_image_retention_events_image_created", "shelf_image_retention_events", ["shelf_image_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_shelf_image_retention_events_image_created", table_name="shelf_image_retention_events")
    op.drop_index("ix_shelf_image_retention_events_created_at", table_name="shelf_image_retention_events")
    op.drop_index("ix_shelf_image_retention_events_actor_user_id", table_name="shelf_image_retention_events")
    op.drop_index("ix_shelf_image_retention_events_shelf_image_id", table_name="shelf_image_retention_events")
    op.drop_table("shelf_image_retention_events")
