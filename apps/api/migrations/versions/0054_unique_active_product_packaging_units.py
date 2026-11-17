"""Enforce one active ordering and replenishment unit per product."""

from alembic import op


revision = "0054_unique_active_product_packaging_units"
down_revision = "0053_inventory_movement_append_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX uq_product_packaging_active_ordering_unit
        ON product_packaging_levels (product_id)
        WHERE is_active IS TRUE AND is_ordering_unit IS TRUE
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_product_packaging_active_replenishment_unit
        ON product_packaging_levels (product_id)
        WHERE is_active IS TRUE AND is_replenishment_unit IS TRUE
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_product_packaging_active_replenishment_unit")
    op.execute("DROP INDEX IF EXISTS uq_product_packaging_active_ordering_unit")
