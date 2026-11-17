"""Protect append-only detection reviews and OCR-derived evidence from direct deletes."""

from alembic import op

revision = "0030_detection_ocr_audit_restrict"
down_revision = "0029_image_derived_evidence_restrict"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_detection_delete_with_audit()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM detection_sku_reviews
                    WHERE detection_id = OLD.id
                ) OR EXISTS (
                    SELECT 1 FROM shelf_image_ocr_evidence
                    WHERE detection_id = OLD.id
                ) OR EXISTS (
                    SELECT 1 FROM shelf_image_ocr_matches
                    WHERE detection_id = OLD.id
                ) OR EXISTS (
                    SELECT 1 FROM shelf_image_fused_evidence
                    WHERE detection_id = OLD.id
                ) THEN
                    RAISE EXCEPTION
                        'detection has review or derived evidence records'
                        USING ERRCODE = '23503';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_detection_audit_delete_restrict
            BEFORE DELETE ON shelf_image_detections
            FOR EACH ROW
            EXECUTE FUNCTION prevent_detection_delete_with_audit()
        """)
        op.execute("""
            CREATE FUNCTION prevent_ocr_run_delete_with_evidence()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM shelf_image_ocr_evidence
                    WHERE run_id = OLD.id
                ) OR EXISTS (
                    SELECT 1 FROM shelf_image_ocr_matches
                    WHERE run_id = OLD.id
                ) OR EXISTS (
                    SELECT 1 FROM shelf_image_fused_evidence
                    WHERE ocr_run_id = OLD.id
                ) THEN
                    RAISE EXCEPTION
                        'OCR run has evidence or matching records'
                        USING ERRCODE = '23503';
                END IF;
                RETURN OLD;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_ocr_run_evidence_delete_restrict
            BEFORE DELETE ON shelf_image_ocr_runs
            FOR EACH ROW
            EXECUTE FUNCTION prevent_ocr_run_delete_with_evidence()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_detection_audit_delete_restrict
            BEFORE DELETE ON shelf_image_detections
            WHEN EXISTS (
                SELECT 1 FROM detection_sku_reviews WHERE detection_id = OLD.id
            ) OR EXISTS (
                SELECT 1 FROM shelf_image_ocr_evidence WHERE detection_id = OLD.id
            ) OR EXISTS (
                SELECT 1 FROM shelf_image_ocr_matches WHERE detection_id = OLD.id
            ) OR EXISTS (
                SELECT 1 FROM shelf_image_fused_evidence WHERE detection_id = OLD.id
            )
            BEGIN
                SELECT RAISE(ABORT, 'detection has review or derived evidence records');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_ocr_run_evidence_delete_restrict
            BEFORE DELETE ON shelf_image_ocr_runs
            WHEN EXISTS (
                SELECT 1 FROM shelf_image_ocr_evidence WHERE run_id = OLD.id
            ) OR EXISTS (
                SELECT 1 FROM shelf_image_ocr_matches WHERE run_id = OLD.id
            ) OR EXISTS (
                SELECT 1 FROM shelf_image_fused_evidence WHERE ocr_run_id = OLD.id
            )
            BEGIN
                SELECT RAISE(ABORT, 'OCR run has evidence or matching records');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_ocr_run_evidence_delete_restrict ON shelf_image_ocr_runs")
        op.execute("DROP FUNCTION IF EXISTS prevent_ocr_run_delete_with_evidence()")
        op.execute("DROP TRIGGER IF EXISTS trg_detection_audit_delete_restrict ON shelf_image_detections")
        op.execute("DROP FUNCTION IF EXISTS prevent_detection_delete_with_audit()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_ocr_run_evidence_delete_restrict")
        op.execute("DROP TRIGGER IF EXISTS trg_detection_audit_delete_restrict")
