"""Preserve shelf ownership of source images used by embedding exemplars."""

from alembic import op


revision = "0100_embedding_source_image_shelf_lineage"
down_revision = "0099_shelf_reconciliation_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_embedding_source_image_shelf_change_0100()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NEW.shelf_id IS DISTINCT FROM OLD.shelf_id
                   AND EXISTS (
                       SELECT 1
                       FROM product_embedding_exemplars
                       WHERE shelf_image_id = OLD.id
                   ) THEN
                    RAISE EXCEPTION
                        'shelf image shelf cannot change while embedding exemplars reference it'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_embedding_shelf_lineage_0100
            BEFORE UPDATE OF shelf_id ON shelf_images
            FOR EACH ROW
            EXECUTE FUNCTION prevent_embedding_source_image_shelf_change_0100()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_image_embedding_shelf_lineage_0100
            BEFORE UPDATE OF shelf_id ON shelf_images
            WHEN NEW.shelf_id IS NOT OLD.shelf_id
             AND EXISTS (
                SELECT 1
                FROM product_embedding_exemplars
                WHERE shelf_image_id = OLD.id
             )
            BEGIN
                SELECT RAISE(
                    ABORT,
                    'shelf image shelf cannot change while embedding exemplars reference it'
                );
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_shelf_image_embedding_shelf_lineage_0100 ON shelf_images"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS prevent_embedding_source_image_shelf_change_0100()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_shelf_image_embedding_shelf_lineage_0100"
        )
