"""Store shelf targets and minimum display levels in product base units."""

from alembic import op
import sqlalchemy as sa

revision = "0090_shelf_product_decimal_quantities"
down_revision = "0089_inventory_movement_base_unit_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.alter_column(
            "shelf_products",
            "target_quantity",
            existing_type=sa.Integer(),
            type_=sa.Numeric(12, 3),
            existing_nullable=False,
            postgresql_using="target_quantity::numeric(12, 3)",
        )
        op.alter_column(
            "shelf_products",
            "min_display_quantity",
            existing_type=sa.Integer(),
            type_=sa.Numeric(12, 3),
            existing_nullable=False,
            postgresql_using="min_display_quantity::numeric(12, 3)",
        )
    else:
        with op.batch_alter_table("shelf_products") as batch:
            batch.alter_column(
                "target_quantity",
                existing_type=sa.Integer(),
                type_=sa.Numeric(12, 3),
                existing_nullable=False,
            )
            batch.alter_column(
                "min_display_quantity",
                existing_type=sa.Integer(),
                type_=sa.Numeric(12, 3),
                existing_nullable=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    fractional = bind.exec_driver_sql(
        """
        SELECT id
        FROM shelf_products
        WHERE target_quantity != CAST(target_quantity AS INTEGER)
           OR min_display_quantity != CAST(min_display_quantity AS INTEGER)
        LIMIT 1
        """
    ).first()
    if fractional is not None:
        raise RuntimeError(
            "Cannot downgrade shelf product quantities while fractional base-unit values exist"
        )

    if bind.dialect.name == "postgresql":
        op.alter_column(
            "shelf_products",
            "target_quantity",
            existing_type=sa.Numeric(12, 3),
            type_=sa.Integer(),
            existing_nullable=False,
            postgresql_using="target_quantity::integer",
        )
        op.alter_column(
            "shelf_products",
            "min_display_quantity",
            existing_type=sa.Numeric(12, 3),
            type_=sa.Integer(),
            existing_nullable=False,
            postgresql_using="min_display_quantity::integer",
        )
    else:
        with op.batch_alter_table("shelf_products") as batch:
            batch.alter_column(
                "target_quantity",
                existing_type=sa.Numeric(12, 3),
                type_=sa.Integer(),
                existing_nullable=False,
            )
            batch.alter_column(
                "min_display_quantity",
                existing_type=sa.Numeric(12, 3),
                type_=sa.Integer(),
                existing_nullable=False,
            )
