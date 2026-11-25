"""Extend image deletion guard to OCR and visual-derived records."""

from alembic import op

revision = "0029_image_derived_evidence_restrict"
down_revision = "0028_embedding_source_image_restrict"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_shelf_image_delete_with_embedding_exemplars()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM product_embedding_exemplars
                    WHERE shelf_image_id = OLD.id
                ) OR EXISTS (
                    SELECT 1 FROM shelf_image_detections
                    WHERE shelf_image_id = OLD.id
                ) OR EXISTS (
                    SELECT 1 FROM shelf_image_ocr_runs
                    WHERE shelf_image_id = OLD.id
                ) THEN
                    RAISE EXCEPTION
                        'shelf image has derived evidence records'
                        USING ERRCODE = '23503';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_embedding_source_restrict")
        op.execute("""
            CREATE TRIGGER trg_shelf_image_embedding_source_restrict
            BEFORE DELETE ON shelf_images
            WHEN EXISTS (
                SELECT 1 FROM product_embedding_exemplars
                WHERE shelf_image_id = OLD.id
            ) OR EXISTS (
                SELECT 1 FROM shelf_image_detections
                WHERE shelf_image_id = OLD.id
            ) OR EXISTS (
                SELECT 1 FROM shelf_image_ocr_runs
                WHERE shelf_image_id = OLD.id
            )
            BEGIN
                SELECT RAISE(ABORT, 'shelf image has derived evidence records');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_shelf_image_delete_with_embedding_exemplars()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM product_embedding_exemplars
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
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_embedding_source_restrict")
        op.execute("""
            CREATE TRIGGER trg_shelf_image_embedding_source_restrict
            BEFORE DELETE ON shelf_images
            WHEN EXISTS (
                SELECT 1 FROM product_embedding_exemplars
                WHERE shelf_image_id = OLD.id
            )
            BEGIN
                SELECT RAISE(ABORT, 'shelf image has derived embedding exemplars');
            END
        """)
