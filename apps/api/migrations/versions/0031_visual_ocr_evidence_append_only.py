"""Make human review and visual/OCR provenance records append-only."""

from alembic import op

revision = "0031_visual_ocr_evidence_append_only"
down_revision = "0030_detection_ocr_audit_restrict"
branch_labels = None
depends_on = None

TABLES = (
    "detection_sku_reviews",
    "shelf_image_ocr_runs",
    "shelf_image_ocr_evidence",
    "shelf_image_ocr_matches",
    "shelf_image_fused_evidence",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_visual_ocr_evidence_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION
                    'visual/OCR provenance records are append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        for table in TABLES:
            op.execute(f"""
                CREATE TRIGGER trg_{table}_append_only
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION prevent_visual_ocr_evidence_mutation()
            """)
    elif bind.dialect.name == "sqlite":
        for table in TABLES:
            op.execute(f"""
                CREATE TRIGGER trg_{table}_no_update
                BEFORE UPDATE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'visual/OCR provenance records are append-only');
                END
            """)
            op.execute(f"""
                CREATE TRIGGER trg_{table}_no_delete
                BEFORE DELETE ON {table}
                BEGIN
                    SELECT RAISE(ABORT, 'visual/OCR provenance records are append-only');
                END
            """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
        op.execute("DROP FUNCTION IF EXISTS prevent_visual_ocr_evidence_mutation()")
    elif bind.dialect.name == "sqlite":
        for table in TABLES:
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete")
