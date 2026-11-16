"""Persist parent-child lineage between external artifact references.

The composite self-reference keeps parent and child attached to the same
source image and store. Existing declarations remain roots (NULL parent).
"""
from alembic import op
import sqlalchemy as sa

revision = "0045_artifact_reference_parent_lineage"
down_revision = "0044_fix_manifest_json_null_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shelf_image_artifact_references",
        sa.Column("parent_reference_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_artifact_reference_parent_lineage",
        "shelf_image_artifact_references",
        "shelf_image_artifact_references",
        ["parent_reference_id", "shelf_image_id", "store_id"],
        ["id", "shelf_image_id", "store_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_artifact_reference_parent_not_self",
        "shelf_image_artifact_references",
        "parent_reference_id IS NULL OR parent_reference_id <> id",
    )
    op.create_index(
        "ix_artifact_reference_parent_reference_id",
        "shelf_image_artifact_references",
        ["parent_reference_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_artifact_reference_parent_reference_id",
        table_name="shelf_image_artifact_references",
    )
    op.drop_constraint(
        "ck_artifact_reference_parent_not_self",
        "shelf_image_artifact_references",
        type_="check",
    )
    op.drop_constraint(
        "fk_artifact_reference_parent_lineage",
        "shelf_image_artifact_references",
        type_="foreignkey",
    )
    op.drop_column("shelf_image_artifact_references", "parent_reference_id")
