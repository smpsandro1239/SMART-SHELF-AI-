"""Add optional SKU attribution to shelf observations."""
from alembic import op
import sqlalchemy as sa

revision = "0026_observation_product_attribution"
down_revision = "0025_shelf_image_legal_hold_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column("product_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_observations_product_id_products",
        "observations",
        "products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_observations_product_id",
        "observations",
        ["product_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_observations_product_id", table_name="observations")
    op.drop_constraint(
        "fk_observations_product_id_products",
        "observations",
        type_="foreignkey",
    )
    op.drop_column("observations", "product_id")
