"""Persist measured shelf quantity on observations."""
from alembic import op
import sqlalchemy as sa

revision = "0010_observed_shelf_quantity"
down_revision = "0009_shelf_image_analysis_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column("observed_quantity", sa.Numeric(12, 3), nullable=True),
    )
    op.create_check_constraint(
        "ck_observation_quantity_nonnegative",
        "observations",
        "observed_quantity IS NULL OR observed_quantity >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_observation_quantity_nonnegative",
        "observations",
        type_="check",
    )
    op.drop_column("observations", "observed_quantity")
