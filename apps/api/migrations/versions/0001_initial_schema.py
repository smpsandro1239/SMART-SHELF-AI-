"""Create initial store, shelf and observation schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_stores_code", "stores", ["code"], unique=True)

    op.create_table(
        "zones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
    )
    op.create_index("ix_zones_store_id", "zones", ["store_id"])

    op.create_table(
        "shelves",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("zone_id", sa.Integer(), sa.ForeignKey("zones.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("description", sa.String(length=250), nullable=True),
    )
    op.create_index("ix_shelves_zone_id", "shelves", ["zone_id"])
    op.create_index("ix_shelves_code", "shelves", ["code"])

    op.create_table(
        "observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=True),
    )
    op.create_index("ix_observations_shelf_id", "observations", ["shelf_id"])
    op.create_index("ix_observations_status", "observations", ["status"])
    op.create_index("ix_observations_observed_at", "observations", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_observations_observed_at", table_name="observations")
    op.drop_index("ix_observations_status", table_name="observations")
    op.drop_index("ix_observations_shelf_id", table_name="observations")
    op.drop_table("observations")
    op.drop_index("ix_shelves_code", table_name="shelves")
    op.drop_index("ix_shelves_zone_id", table_name="shelves")
    op.drop_table("shelves")
    op.drop_index("ix_zones_store_id", table_name="zones")
    op.drop_table("zones")
    op.drop_index("ix_stores_code", table_name="stores")
    op.drop_table("stores")
