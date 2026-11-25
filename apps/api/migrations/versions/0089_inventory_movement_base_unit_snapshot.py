"""Freeze the product base unit on every newly recorded inventory movement."""

from alembic import op
import sqlalchemy as sa

revision = "0089_inventory_movement_base_unit_snapshot"
down_revision = "0088_inventory_movement_available_source_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "inventory_movements",
        sa.Column("unit_code", sa.String(length=30), nullable=True),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION guard_inventory_movement_unit_0089()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $function$
            BEGIN
                IF NEW.unit_code IS NULL
                   OR length(trim(NEW.unit_code)) = 0
                   OR NOT EXISTS (
                       SELECT 1
                       FROM products product
                       WHERE product.id = NEW.product_id
                         AND product.unit = NEW.unit_code
                   )
                THEN
                    RAISE EXCEPTION 'inventory movement unit must match the product base unit'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_unit_0089
            BEFORE INSERT ON inventory_movements
            FOR EACH ROW EXECUTE FUNCTION guard_inventory_movement_unit_0089()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_inventory_movement_unit_0089
            BEFORE INSERT ON inventory_movements
            WHEN NEW.unit_code IS NULL
              OR length(trim(NEW.unit_code)) = 0
              OR NOT EXISTS (
                  SELECT 1
                  FROM products product
                  WHERE product.id = NEW.product_id
                    AND product.unit = NEW.unit_code
              )
            BEGIN
                SELECT RAISE(ABORT, 'inventory movement unit must match the product base unit');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_movement_unit_0089 "
            "ON inventory_movements"
        )
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_movement_unit_0089()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_movement_unit_0089")
    op.drop_column("inventory_movements", "unit_code")
