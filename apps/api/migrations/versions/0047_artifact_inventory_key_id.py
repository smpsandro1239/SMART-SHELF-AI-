"""Persist the HMAC key identifier used by each immutable inventory snapshot.

Existing snapshots are explicitly marked as legacy so their version-1
canonical payload and historical source-wide key configuration remain verifiable.
"""
from alembic import op
import sqlalchemy as sa


revision = "0047_artifact_inventory_key_id"
down_revision = "0046_artifact_parent_lineage_immutable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shelf_image_artifact_inventory_snapshots",
        sa.Column(
            "key_id",
            sa.String(length=64),
            nullable=False,
            server_default="legacy",
        ),
    )
    op.create_check_constraint(
        "ck_artifact_inventory_key_id_format",
        "shelf_image_artifact_inventory_snapshots",
        "length(key_id) BETWEEN 1 AND 64",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_artifact_inventory_key_id_format",
        "shelf_image_artifact_inventory_snapshots",
        type_="check",
    )
    op.drop_column("shelf_image_artifact_inventory_snapshots", "key_id")
