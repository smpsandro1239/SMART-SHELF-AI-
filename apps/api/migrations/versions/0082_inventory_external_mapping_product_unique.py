"""Backfill uniqueness for store/source/internal-product external mappings.

Revision 0078 originally shipped without the internal-product uniqueness rule.
This additive revision repairs already-upgraded databases while fresh installs
may already have the equivalent table constraint from the corrected 0078 file.
"""
from alembic import op
import sqlalchemy as sa

revision = "0082_inventory_external_mapping_product_unique"
down_revision = "0081_inventory_external_mapping_identity_guard"
branch_labels = None
depends_on = None

CONSTRAINT_NAME = "uq_inventory_external_mapping_product"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    unique_constraints = {
        item.get("name") for item in inspector.get_unique_constraints(
            "inventory_external_product_mappings"
        )
    }
    indexes = {
        item.get("name") for item in inspector.get_indexes(
            "inventory_external_product_mappings"
        )
    }
    if CONSTRAINT_NAME in unique_constraints or CONSTRAINT_NAME in indexes:
        return

    duplicates = bind.execute(sa.text("""
        SELECT store_id, source, product_id, COUNT(*) AS occurrences
        FROM inventory_external_product_mappings
        GROUP BY store_id, source, product_id
        HAVING COUNT(*) > 1
        LIMIT 1
    """)).first()
    if duplicates:
        raise RuntimeError(
            "Cannot enforce one external mapping per internal product: "
            "duplicate store/source/product mappings require manual review."
        )

    op.create_index(
        CONSTRAINT_NAME,
        "inventory_external_product_mappings",
        ["store_id", "source", "product_id"],
        unique=True,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {
        item.get("name") for item in inspector.get_indexes(
            "inventory_external_product_mappings"
        )
    }
    if CONSTRAINT_NAME in indexes:
        op.drop_index(CONSTRAINT_NAME, table_name="inventory_external_product_mappings")
