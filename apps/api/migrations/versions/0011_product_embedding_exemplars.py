"""Persist reviewed product embedding exemplars."""
from alembic import op
import sqlalchemy as sa

revision = "0011_product_embedding_exemplars"
down_revision = "0010_observed_shelf_quantity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "product_embedding_exemplars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shelf_image_id", sa.Integer(), sa.ForeignKey("shelf_images.id", ondelete="SET NULL"), nullable=True),
        sa.Column("embedding", sa.JSON(), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=False),
        sa.Column("image_sha256", sa.String(length=64), nullable=False),
        sa.Column("licence", sa.String(length=250), nullable=False),
        sa.Column("review_status", sa.String(length=12), nullable=False, server_default="PENDING"),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("product_id", "model_version", "image_sha256", name="uq_product_embedding_product_model_image"),
        sa.CheckConstraint("review_status IN ('PENDING', 'APPROVED', 'REJECTED')", name="ck_product_embedding_review_status"),
        sa.CheckConstraint("length(image_sha256) = 64", name="ck_product_embedding_image_sha256_length"),
    )
    op.create_index("ix_product_embedding_exemplars_product_id", "product_embedding_exemplars", ["product_id"])
    op.create_index("ix_product_embedding_exemplars_shelf_image_id", "product_embedding_exemplars", ["shelf_image_id"])
    op.create_index("ix_product_embedding_exemplars_model_version", "product_embedding_exemplars", ["model_version"])
    op.create_index("ix_product_embedding_exemplars_image_sha256", "product_embedding_exemplars", ["image_sha256"])
    op.create_index("ix_product_embedding_exemplars_review_status", "product_embedding_exemplars", ["review_status"])


def downgrade() -> None:
    op.drop_index("ix_product_embedding_exemplars_review_status", table_name="product_embedding_exemplars")
    op.drop_index("ix_product_embedding_exemplars_image_sha256", table_name="product_embedding_exemplars")
    op.drop_index("ix_product_embedding_exemplars_model_version", table_name="product_embedding_exemplars")
    op.drop_index("ix_product_embedding_exemplars_shelf_image_id", table_name="product_embedding_exemplars")
    op.drop_index("ix_product_embedding_exemplars_product_id", table_name="product_embedding_exemplars")
    op.drop_table("product_embedding_exemplars")
