"""Persist parent-child lineage between external artifact references.

The composite self-reference keeps parent and child attached to the same
source image and store. Existing declarations remain roots (NULL parent).
"""
from alembic import op
import sqlalchemy as sa


revision = "0045_artifact_reference_parent_lineage"
down_revision = "0044_fix_manifest_json_null_check"
branch_labels = None
depends_on = None


def _ensure_index(name: str, table: str, columns: list[str], *, unique: bool = False) -> None:
    """Create an index unless an identical index already exists.

    Reuse a pre-provisioned index only when its definition matches exactly.
    A conflicting relation with the same name is a migration error.
    """
    bind = op.get_bind()
    existing = {
        index["name"]: index
        for index in sa.inspect(bind).get_indexes(table)
        if index.get("name")
    }.get(name)
    if existing is not None:
        if existing.get("column_names") != columns or bool(existing.get("unique")) != unique:
            raise RuntimeError(
                f"existing index {name} on {table} has an unexpected definition"
            )
        return
    op.create_index(name, table, columns, unique=unique)

def upgrade() -> None:
    bind = op.get_bind()
    op.add_column(
        "shelf_image_artifact_references",
        sa.Column("parent_reference_id", sa.Integer(), nullable=True),
    )
    # PostgreSQL requires a unique target for the composite self-FK.
    # The leading id is already unique, but the full referenced tuple must
    # have an explicit unique index for portable constraint validation.
    _ensure_index(
        "uq_shelf_image_artifact_reference_lineage",
        "shelf_image_artifact_references",
        ["id", "shelf_image_id", "store_id"],
        unique=True,
    )
    _ensure_index(
        "ix_artifact_reference_parent_reference_id",
        "shelf_image_artifact_references",
        ["parent_reference_id"],
    )

    if bind.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_artifact_reference_parent_lineage",
            "shelf_image_artifact_references",
            "shelf_image_artifact_references",
            ["parent_reference_id", "shelf_image_id", "store_id"],
            ["id", "shelf_image_id", "store_id"],
            ondelete="RESTRICT",
        )
        op.create_check_constraint(
            "ck_artifact_reference_parent_not_self",
            "shelf_image_artifact_references",
            "parent_reference_id IS NULL OR parent_reference_id <> id",
        )
    elif bind.dialect.name == "sqlite":
        # SQLite cannot add a composite FK to an existing table without a
        # table rebuild. Triggers preserve equivalent insert-time guarantees
        # without rebuilding the table and losing its append-only triggers.
        op.execute("""
            CREATE TRIGGER trg_artifact_reference_parent_lineage_insert
            BEFORE INSERT ON shelf_image_artifact_references
            WHEN NEW.parent_reference_id IS NOT NULL
            BEGIN
                SELECT CASE
                    WHEN NEW.parent_reference_id = NEW.id
                    THEN RAISE(ABORT, 'artifact reference cannot be its own parent')
                    WHEN NOT EXISTS (
                        SELECT 1
                        FROM shelf_image_artifact_references parent
                        WHERE parent.id = NEW.parent_reference_id
                          AND parent.shelf_image_id = NEW.shelf_image_id
                          AND parent.store_id = NEW.store_id
                    )
                    THEN RAISE(ABORT, 'artifact parent must belong to the same image and store')
                END;
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "ck_artifact_reference_parent_not_self",
            "shelf_image_artifact_references",
            type_="check",
        )
        op.drop_constraint(
            "fk_artifact_reference_parent_lineage",
            "shelf_image_artifact_references",
            type_="foreignkey",
        )
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_artifact_reference_parent_lineage_insert")

    op.drop_index(
        "ix_artifact_reference_parent_reference_id",
        table_name="shelf_image_artifact_references",
    )
    op.drop_index(
        "uq_shelf_image_artifact_reference_lineage",
        table_name="shelf_image_artifact_references",
    )
    op.drop_column("shelf_image_artifact_references", "parent_reference_id")
