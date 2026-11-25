"""Persist expected front-facing count in versioned shelf planogram cells."""
from alembic import op
import sqlalchemy as sa

revision = "0068_shelf_planogram_expected_facings"
down_revision = "0067_shelf_planograms"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shelf_planogram_cells",
        sa.Column("expected_facings", sa.Integer(), nullable=True),
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_shelf_planogram_cell_expected_facings",
            "shelf_planogram_cells",
            "expected_facings IS NULL OR (expected_facings > 0 AND expected_product_id IS NOT NULL)",
        )
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_expected_facings_insert_0068
            BEFORE INSERT ON shelf_planogram_cells
            WHEN NEW.expected_facings IS NOT NULL
                 AND (NEW.expected_facings <= 0 OR NEW.expected_product_id IS NULL)
            BEGIN
                SELECT RAISE(ABORT, 'expected_facings requires a positive count and expected SKU');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_planogram_expected_facings_update_0068
            BEFORE UPDATE OF expected_facings, expected_product_id ON shelf_planogram_cells
            WHEN NEW.expected_facings IS NOT NULL
                 AND (NEW.expected_facings <= 0 OR NEW.expected_product_id IS NULL)
            BEGIN
                SELECT RAISE(ABORT, 'expected_facings requires a positive count and expected SKU');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "ck_shelf_planogram_cell_expected_facings",
            "shelf_planogram_cells",
            type_="check",
        )
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_planogram_expected_facings_update_0068")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_planogram_expected_facings_insert_0068")
    op.drop_column("shelf_planogram_cells", "expected_facings")
