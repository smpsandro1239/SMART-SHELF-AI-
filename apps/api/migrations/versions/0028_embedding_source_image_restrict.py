"""Preserve source-image lineage for derived SKU embedding exemplars."""

from alembic import op

revision = "0028_embedding_source_image_restrict"
down_revision = "0027_observation_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_shelf_image_delete_with_embedding_exemplars()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM product_embedding_exemplars
                    WHERE shelf_image_id = OLD.id
                ) THEN
                    RAISE EXCEPTION
                        'shelf image has derived embedding exemplars'
                        USING ERRCODE = '23503';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_embedding_source_restrict
            BEFORE DELETE ON shelf_images
            FOR EACH ROW
            EXECUTE FUNCTION prevent_shelf_image_delete_with_embedding_exemplars()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_image_embedding_source_restrict
            BEFORE DELETE ON shelf_images
            WHEN EXISTS (
                SELECT 1
                FROM product_embedding_exemplars
                WHERE shelf_image_id = OLD.id
            )
            BEGIN
                SELECT RAISE(ABORT, 'shelf image has derived embedding exemplars');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_shelf_image_embedding_source_restrict ON shelf_images"
        )
        op.execute(
            "DROP FUNCTION IF EXISTS prevent_shelf_image_delete_with_embedding_exemplars()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_shelf_image_embedding_source_restrict"
        )
