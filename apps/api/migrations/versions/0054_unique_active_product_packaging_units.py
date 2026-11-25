"""Enforce one active ordering and replenishment unit per product."""

import sqlalchemy as sa
from alembic import op


revision = "0054_unique_active_product_packaging_units"
down_revision = "0053_inventory_movement_append_only"
branch_labels = None
depends_on = None


def _find_duplicate_product_ids(connection, flag_column: str) -> list[tuple[int, int]]:
    """Return a bounded list of products violating one active packaging-unit role."""
    if flag_column not in {"is_ordering_unit", "is_replenishment_unit"}:
        raise ValueError("Unsupported packaging-unit flag")
    rows = connection.execute(
        sa.text(
            f"""
            SELECT product_id, COUNT(*) AS duplicate_count
            FROM product_packaging_levels
            WHERE is_active IS TRUE AND {flag_column} IS TRUE
            GROUP BY product_id
            HAVING COUNT(*) > 1
            ORDER BY product_id
            LIMIT 20
            """
        )
    ).all()
    return [(int(row.product_id), int(row.duplicate_count)) for row in rows]


def upgrade() -> None:
    connection = op.get_bind()
    duplicates = {
        "ordering": _find_duplicate_product_ids(connection, "is_ordering_unit"),
        "replenishment": _find_duplicate_product_ids(connection, "is_replenishment_unit"),
    }
    conflicts = [
        f"{role}: " + ", ".join(
            f"product_id={product_id} ({count} active rows)"
            for product_id, count in rows
        )
        for role, rows in duplicates.items()
        if rows
    ]
    if conflicts:
        raise RuntimeError(
            "Cannot apply migration 0054: duplicate active product packaging units "
            "must be reconciled before creating unique indexes. "
            + "; ".join(conflicts)
            + ". No rows were modified."
        )

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
