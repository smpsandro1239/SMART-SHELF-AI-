"""Reject output publication when any immutable source is restricted or held."""
from alembic import op
revision = "0064_dataset_output_source_eligibility"
down_revision = "0063_dataset_job_output_publications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION enforce_dataset_job_output_source_eligibility_0064()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE source_count INTEGER;
            BEGIN
                PERFORM si.id FROM dataset_execution_job_sources src
                JOIN shelf_images si ON si.id = src.shelf_image_id
                JOIN shelves sh ON sh.id = si.shelf_id
                JOIN zones z ON z.id = sh.zone_id
                WHERE src.job_id = NEW.job_id
                ORDER BY si.id, sh.id, z.id
                FOR SHARE OF si, sh, z;
                SELECT COUNT(*) INTO source_count FROM dataset_execution_job_sources WHERE job_id = NEW.job_id;
                IF source_count = 0 THEN
                    RAISE EXCEPTION 'output publication requires immutable job sources' USING ERRCODE = '23514';
                END IF;
                IF EXISTS (
                    SELECT 1 FROM dataset_execution_job_sources src
                    LEFT JOIN shelf_images si ON si.id = src.shelf_image_id
                    LEFT JOIN shelves sh ON sh.id = si.shelf_id
                    LEFT JOIN zones z ON z.id = sh.zone_id
                    WHERE src.job_id = NEW.job_id AND (
                        si.id IS NULL OR sh.id IS NULL OR z.id IS NULL OR z.store_id <> src.store_id
                        OR si.sha256 <> src.source_image_sha256
                        OR si.retention_status <> 'ACTIVE' OR si.legal_hold IS TRUE
                    )
                ) THEN
                    RAISE EXCEPTION 'output publication source is missing, changed, restricted or under legal hold'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_output_source_eligibility_0064
            BEFORE INSERT ON dataset_execution_job_output_publications
            FOR EACH ROW EXECUTE FUNCTION enforce_dataset_job_output_source_eligibility_0064()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_job_output_source_eligibility_0064
            BEFORE INSERT ON dataset_execution_job_output_publications
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM dataset_execution_job_sources WHERE job_id = NEW.job_id
                ) THEN RAISE(ABORT, 'output publication requires immutable job sources') END;
                SELECT CASE WHEN EXISTS (
                    SELECT 1 FROM dataset_execution_job_sources src
                    LEFT JOIN shelf_images si ON si.id = src.shelf_image_id
                    LEFT JOIN shelves sh ON sh.id = si.shelf_id
                    LEFT JOIN zones z ON z.id = sh.zone_id
                    WHERE src.job_id = NEW.job_id AND (
                        si.id IS NULL OR sh.id IS NULL OR z.id IS NULL OR z.store_id <> src.store_id
                        OR si.sha256 <> src.source_image_sha256
                        OR si.retention_status <> 'ACTIVE' OR si.legal_hold <> 0
                    )
                ) THEN RAISE(ABORT, 'output publication source is missing, changed, restricted or under legal hold') END;
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_output_source_eligibility_0064 ON dataset_execution_job_output_publications")
        op.execute("DROP FUNCTION IF EXISTS enforce_dataset_job_output_source_eligibility_0064()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_output_source_eligibility_0064")
