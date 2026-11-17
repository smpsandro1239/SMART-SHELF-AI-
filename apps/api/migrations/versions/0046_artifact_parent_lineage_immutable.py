"""Prevent mutation of an external artifact's persisted parent link.

Parent references must point to an already-existing artifact at INSERT time.
Allowing the parent link to change later would bypass the append-only lineage
contract and could introduce cycles or rewrite the provenance graph.
"""
from alembic import op


revision = "0046_artifact_parent_lineage_immutable"
down_revision = "0045_artifact_reference_parent_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_artifact_parent_lineage_update()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NEW.parent_reference_id IS DISTINCT FROM OLD.parent_reference_id THEN
                    RAISE EXCEPTION 'artifact parent lineage is immutable after declaration'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_artifact_parent_lineage_immutable
            BEFORE UPDATE OF parent_reference_id ON shelf_image_artifact_references
            FOR EACH ROW
            EXECUTE FUNCTION prevent_artifact_parent_lineage_update()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_artifact_parent_lineage_immutable
            BEFORE UPDATE OF parent_reference_id ON shelf_image_artifact_references
            WHEN NEW.parent_reference_id IS NOT OLD.parent_reference_id
            BEGIN
                SELECT RAISE(ABORT, 'artifact parent lineage is immutable after declaration');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_artifact_parent_lineage_immutable "
            "ON shelf_image_artifact_references"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS prevent_artifact_parent_lineage_update()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_artifact_parent_lineage_immutable")
