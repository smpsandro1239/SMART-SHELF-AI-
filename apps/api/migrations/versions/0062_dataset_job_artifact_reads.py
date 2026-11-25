"""Audit and database-guard per-request reads of dataset job source images."""

from alembic import op
import sqlalchemy as sa

revision = "0062_dataset_job_artifact_reads"
down_revision = "0061_dataset_worker_request_nonces"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_execution_job_artifact_reads",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("shelf_image_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=160), nullable=False),
        sa.Column("credential_id", sa.String(length=32), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("source_image_sha256", sa.String(length=64), nullable=False),
        sa.Column("bytes_read", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["dataset_execution_jobs.id"], name="fk_dataset_job_artifact_reads_job", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shelf_image_id"], ["shelf_images.id"], name="fk_dataset_job_artifact_reads_image", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["worker_id"], ["dataset_workers.worker_id"], name="fk_dataset_job_artifact_reads_worker", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_id"], ["dataset_worker_credentials.credential_id"], name="fk_dataset_job_artifact_reads_credential", ondelete="RESTRICT"),
        sa.CheckConstraint("fencing_token > 0", name="ck_dataset_job_artifact_read_fencing_positive"),
        sa.CheckConstraint("length(source_image_sha256) = 64", name="ck_dataset_job_artifact_read_digest"),
        sa.CheckConstraint("bytes_read > 0", name="ck_dataset_job_artifact_read_bytes_positive"),
    )
    op.create_index("ix_dataset_job_artifact_reads_job_created", "dataset_execution_job_artifact_reads", ["job_id", "created_at", "id"])
    op.create_index("ix_dataset_job_artifact_reads_image_created", "dataset_execution_job_artifact_reads", ["shelf_image_id", "created_at", "id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION enforce_dataset_job_artifact_read_0062()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                job_status TEXT;
                job_lease_owner TEXT;
                lease_token INTEGER;
                lease_expiry TIMESTAMPTZ;
                source_store_id INTEGER;
                source_digest TEXT;
                image_digest TEXT;
                image_status TEXT;
                image_hold BOOLEAN;
                actual_store_id INTEGER;
                worker_status TEXT;
                credential_worker_id TEXT;
                credential_revoked_at TIMESTAMPTZ;
                credential_expiry TIMESTAMPTZ;
                credential_scopes TEXT;
                image_size INTEGER;
            BEGIN
                SELECT status, lease_owner, fencing_token, lease_expires_at
                INTO job_status, job_lease_owner, lease_token, lease_expiry
                FROM dataset_execution_jobs AS j WHERE j.id = NEW.job_id FOR UPDATE OF j;
                IF NOT FOUND OR job_status <> 'LEASED'
                   OR job_lease_owner <> NEW.worker_id
                   OR lease_token <> NEW.fencing_token
                   OR lease_expiry IS NULL OR lease_expiry <= clock_timestamp() THEN
                    RAISE EXCEPTION 'dataset artifact read requires the current unexpired job lease'
                        USING ERRCODE = '23514';
                END IF;

                SELECT store_id, source_image_sha256
                INTO source_store_id, source_digest
                FROM dataset_execution_job_sources
                WHERE job_id = NEW.job_id AND shelf_image_id = NEW.shelf_image_id;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'dataset artifact read is not an immutable job source'
                        USING ERRCODE = '23514';
                END IF;

                SELECT i.sha256, i.retention_status, i.legal_hold, i.file_size_bytes, z.store_id
                INTO image_digest, image_status, image_hold, image_size, actual_store_id
                FROM shelf_images i
                JOIN shelves s ON s.id = i.shelf_id
                JOIN zones z ON z.id = s.zone_id
                WHERE i.id = NEW.shelf_image_id
                FOR UPDATE OF i, s, z;
                IF NOT FOUND OR image_status <> 'ACTIVE' OR image_hold
                   OR actual_store_id <> source_store_id
                   OR image_digest <> source_digest
                   OR NEW.source_image_sha256 <> source_digest
                   OR NEW.bytes_read <> image_size THEN
                    RAISE EXCEPTION 'dataset artifact read source is not eligible or integrity-verified'
                        USING ERRCODE = '23514';
                END IF;

                SELECT w.status, c.worker_id, c.revoked_at, c.expires_at, c.scopes::text
                INTO worker_status, credential_worker_id, credential_revoked_at,
                     credential_expiry, credential_scopes
                FROM dataset_workers w
                JOIN dataset_worker_credentials c ON c.worker_id = w.worker_id
                WHERE w.worker_id = NEW.worker_id AND c.credential_id = NEW.credential_id
                FOR SHARE OF w, c;
                IF NOT FOUND OR worker_status <> 'ACTIVE'
                   OR credential_worker_id <> NEW.worker_id
                   OR credential_revoked_at IS NOT NULL
                   OR credential_expiry <= clock_timestamp()
                   OR NOT (credential_scopes::jsonb @> '["artifacts:read"]'::jsonb) THEN
                    RAISE EXCEPTION 'dataset artifact read requires an active credential with artifacts:read'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_artifact_read_guard_0062
            BEFORE INSERT ON dataset_execution_job_artifact_reads
            FOR EACH ROW EXECUTE FUNCTION enforce_dataset_job_artifact_read_0062()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_dataset_job_artifact_read_mutation_0062()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'dataset job artifact read audit is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_artifact_read_append_only_0062
            BEFORE UPDATE OR DELETE ON dataset_execution_job_artifact_reads
            FOR EACH ROW EXECUTE FUNCTION prevent_dataset_job_artifact_read_mutation_0062()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_job_artifact_read_guard_0062
            BEFORE INSERT ON dataset_execution_job_artifact_reads
            WHEN NOT EXISTS (
                SELECT 1
                FROM dataset_execution_jobs j
                JOIN dataset_execution_job_sources src
                  ON src.job_id = j.id AND src.shelf_image_id = NEW.shelf_image_id
                JOIN shelf_images i ON i.id = NEW.shelf_image_id
                JOIN shelves s ON s.id = i.shelf_id
                JOIN zones z ON z.id = s.zone_id
                JOIN dataset_workers w ON w.worker_id = NEW.worker_id
                JOIN dataset_worker_credentials c
                  ON c.credential_id = NEW.credential_id AND c.worker_id = w.worker_id
                WHERE j.id = NEW.job_id
                  AND j.status = 'LEASED'
                  AND j.lease_owner = NEW.worker_id
                  AND j.fencing_token = NEW.fencing_token
                  AND julianday(j.lease_expires_at) > julianday('now')
                  AND src.store_id = z.store_id
                  AND src.source_image_sha256 = i.sha256
                  AND NEW.source_image_sha256 = src.source_image_sha256
                  AND NEW.bytes_read = i.file_size_bytes
                  AND i.retention_status = 'ACTIVE'
                  AND i.legal_hold = 0
                  AND w.status = 'ACTIVE'
                  AND c.revoked_at IS NULL
                  AND julianday(c.expires_at) > julianday('now')
                  AND EXISTS (
                      SELECT 1 FROM json_each(c.scopes) WHERE value = 'artifacts:read'
                  )
            )
            BEGIN
                SELECT RAISE(ABORT, 'dataset artifact read requires an active lease, source and artifacts:read credential');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_artifact_read_no_update_0062
            BEFORE UPDATE ON dataset_execution_job_artifact_reads
            BEGIN
                SELECT RAISE(ABORT, 'dataset job artifact read audit is append-only');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_artifact_read_no_delete_0062
            BEFORE DELETE ON dataset_execution_job_artifact_reads
            BEGIN
                SELECT RAISE(ABORT, 'dataset job artifact read audit is append-only');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_artifact_read_append_only_0062 ON dataset_execution_job_artifact_reads")
        op.execute("DROP FUNCTION IF EXISTS prevent_dataset_job_artifact_read_mutation_0062()")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_artifact_read_guard_0062 ON dataset_execution_job_artifact_reads")
        op.execute("DROP FUNCTION IF EXISTS enforce_dataset_job_artifact_read_0062()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_artifact_read_no_update_0062")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_artifact_read_no_delete_0062")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_artifact_read_guard_0062")
    op.drop_index("ix_dataset_job_artifact_reads_image_created", table_name="dataset_execution_job_artifact_reads")
    op.drop_index("ix_dataset_job_artifact_reads_job_created", table_name="dataset_execution_job_artifact_reads")
    op.drop_table("dataset_execution_job_artifact_reads")
