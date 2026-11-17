"""Protect immutable lineage of SKU embedding exemplars."""

from alembic import op

revision = "0037_embedding_exemplar_lineage_immutable"
down_revision = "0036_store_external_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION validate_product_embedding_exemplar_lineage()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                source_sha256 VARCHAR(64);
                source_retention_status VARCHAR(20);
            BEGIN
                IF TG_OP = 'UPDATE' THEN
                    IF NEW.product_id IS DISTINCT FROM OLD.product_id
                       OR NEW.shelf_image_id IS DISTINCT FROM OLD.shelf_image_id
                       OR NEW.embedding::text IS DISTINCT FROM OLD.embedding::text
                       OR NEW.embedding_dimension IS DISTINCT FROM OLD.embedding_dimension
                       OR NEW.model_version IS DISTINCT FROM OLD.model_version
                       OR NEW.image_sha256 IS DISTINCT FROM OLD.image_sha256
                       OR NEW.licence IS DISTINCT FROM OLD.licence
                       OR NEW.created_by_user_id IS DISTINCT FROM OLD.created_by_user_id
                       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                        RAISE EXCEPTION 'embedding exemplar source lineage is immutable'
                            USING ERRCODE = '23514';
                    END IF;
                    RETURN NEW;
                END IF;

                IF NEW.shelf_image_id IS NOT NULL THEN
                    SELECT sha256, retention_status
                    INTO source_sha256, source_retention_status
                    FROM shelf_images
                    WHERE id = NEW.shelf_image_id
                    FOR UPDATE;

                    IF NOT FOUND THEN
                        RAISE EXCEPTION 'embedding exemplar source image does not exist'
                            USING ERRCODE = '23503';
                    END IF;
                    IF source_retention_status <> 'ACTIVE' THEN
                        RAISE EXCEPTION 'embedding exemplar source image is not active'
                            USING ERRCODE = '23514';
                    END IF;
                    IF lower(source_sha256) <> lower(NEW.image_sha256) THEN
                        RAISE EXCEPTION 'embedding exemplar SHA-256 does not match source image'
                            USING ERRCODE = '23514';
                    END IF;
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_product_embedding_exemplar_lineage
            BEFORE INSERT OR UPDATE ON product_embedding_exemplars
            FOR EACH ROW EXECUTE FUNCTION validate_product_embedding_exemplar_lineage()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_product_embedding_exemplar_lineage_insert
            BEFORE INSERT ON product_embedding_exemplars
            WHEN NEW.shelf_image_id IS NOT NULL
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM shelf_images
                    WHERE id = NEW.shelf_image_id
                      AND retention_status = 'ACTIVE'
                      AND lower(sha256) = lower(NEW.image_sha256)
                ) THEN RAISE(ABORT, 'embedding exemplar source image is not active or SHA-256 does not match') END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_product_embedding_exemplar_lineage_update
            BEFORE UPDATE ON product_embedding_exemplars
            BEGIN
                SELECT CASE WHEN
                    NEW.product_id IS NOT OLD.product_id
                    OR NEW.shelf_image_id IS NOT OLD.shelf_image_id
                    OR NEW.embedding IS NOT OLD.embedding
                    OR NEW.embedding_dimension IS NOT OLD.embedding_dimension
                    OR NEW.model_version IS NOT OLD.model_version
                    OR NEW.image_sha256 IS NOT OLD.image_sha256
                    OR NEW.licence IS NOT OLD.licence
                    OR NEW.created_by_user_id IS NOT OLD.created_by_user_id
                    OR NEW.created_at IS NOT OLD.created_at
                THEN RAISE(ABORT, 'embedding exemplar source lineage is immutable') END;
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_product_embedding_exemplar_lineage ON product_embedding_exemplars")
        op.execute("DROP FUNCTION IF EXISTS validate_product_embedding_exemplar_lineage()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_product_embedding_exemplar_lineage_update")
        op.execute("DROP TRIGGER IF EXISTS trg_product_embedding_exemplar_lineage_insert")
