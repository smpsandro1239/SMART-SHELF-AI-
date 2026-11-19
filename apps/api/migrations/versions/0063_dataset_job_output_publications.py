"""Audit and database-guard fenced promotion of successful dataset outputs."""

from alembic import op
import sqlalchemy as sa

revision = "0063_dataset_job_output_publications"
down_revision = "0062_dataset_job_artifact_reads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_execution_job_output_publications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(length=160), nullable=False),
        sa.Column("credential_id", sa.String(length=32), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("output_sha256", sa.String(length=64), nullable=False),
        sa.Column("staged_output_reference", sa.String(length=600), nullable=False),
        sa.Column("published_output_reference", sa.String(length=600), nullable=False),
        sa.Column("bytes_published", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["dataset_execution_jobs.id"], name="fk_dataset_job_output_publication_job", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["worker_id"], ["dataset_workers.worker_id"], name="fk_dataset_job_output_publication_worker", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credential_id"], ["dataset_worker_credentials.credential_id"], name="fk_dataset_job_output_publication_credential", ondelete="RESTRICT"),
        sa.CheckConstraint("fencing_token > 0", name="ck_dataset_job_output_publication_fencing_positive"),
        sa.CheckConstraint("length(output_sha256) = 64", name="ck_dataset_job_output_publication_digest"),
        sa.CheckConstraint("bytes_published > 0", name="ck_dataset_job_output_publication_bytes_positive"),
        sa.CheckConstraint("published_output_reference LIKE 'published/%'", name="ck_dataset_job_output_publication_reference"),
        sa.UniqueConstraint("job_id", name="uq_dataset_job_output_publication_job"),
        sa.UniqueConstraint("published_output_reference", name="uq_dataset_job_output_publication_reference"),
    )
    op.create_index("ix_dataset_job_output_publications_worker_created", "dataset_execution_job_output_publications", ["worker_id", "created_at"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION enforce_dataset_job_output_publication_0063()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                j_status TEXT; j_digest TEXT; j_staged TEXT; j_token INTEGER;
                w_status TEXT; c_worker TEXT; c_revoked TIMESTAMPTZ; c_expiry TIMESTAMPTZ; c_scopes TEXT;
                event_worker TEXT; event_token INTEGER; event_digest TEXT;
            BEGIN
                SELECT status, output_sha256, staged_output_reference, fencing_token
                INTO j_status, j_digest, j_staged, j_token
                FROM dataset_execution_jobs WHERE id = NEW.job_id FOR UPDATE;
                IF NOT FOUND OR j_status <> 'SUCCEEDED' OR j_digest <> NEW.output_sha256
                   OR j_staged <> NEW.staged_output_reference OR j_token <> NEW.fencing_token THEN
                    RAISE EXCEPTION 'publication requires matching successful job and fencing token' USING ERRCODE = '23514';
                END IF;
                SELECT worker_id, fencing_token, details->>'output_sha256'
                INTO event_worker, event_token, event_digest
                FROM dataset_execution_job_events
                WHERE job_id = NEW.job_id AND event_type = 'SUCCEEDED'
                ORDER BY sequence_number DESC LIMIT 1;
                IF event_worker IS DISTINCT FROM NEW.worker_id OR event_token IS DISTINCT FROM NEW.fencing_token
                   OR event_digest IS DISTINCT FROM NEW.output_sha256 THEN
                    RAISE EXCEPTION 'publisher does not match successful terminal event' USING ERRCODE = '23514';
                END IF;
                SELECT w.status, c.worker_id, c.revoked_at, c.expires_at, c.scopes::text
                INTO w_status, c_worker, c_revoked, c_expiry, c_scopes
                FROM dataset_workers w JOIN dataset_worker_credentials c ON c.worker_id = w.worker_id
                WHERE w.worker_id = NEW.worker_id AND c.credential_id = NEW.credential_id
                FOR SHARE OF w, c;
                IF NOT FOUND OR w_status <> 'ACTIVE' OR c_worker <> NEW.worker_id
                   OR c_revoked IS NOT NULL OR c_expiry <= clock_timestamp()
                   OR NOT (c_scopes::jsonb @> '["outputs:publish"]'::jsonb) THEN
                    RAISE EXCEPTION 'publication requires active outputs:publish credential' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_output_publication_guard_0063
            BEFORE INSERT ON dataset_execution_job_output_publications
            FOR EACH ROW EXECUTE FUNCTION enforce_dataset_job_output_publication_0063()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_dataset_job_output_publication_mutation_0063()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'dataset job output publication audit is append-only' USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_output_publication_append_only_0063
            BEFORE UPDATE OR DELETE ON dataset_execution_job_output_publications
            FOR EACH ROW EXECUTE FUNCTION prevent_dataset_job_output_publication_mutation_0063()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_job_output_publication_guard_0063
            BEFORE INSERT ON dataset_execution_job_output_publications
            WHEN NOT EXISTS (
                SELECT 1 FROM dataset_execution_jobs j
                JOIN dataset_execution_job_events e ON e.job_id = j.id AND e.event_type = 'SUCCEEDED'
                JOIN dataset_workers w ON w.worker_id = NEW.worker_id
                JOIN dataset_worker_credentials c ON c.credential_id = NEW.credential_id AND c.worker_id = w.worker_id
                WHERE j.id = NEW.job_id AND j.status = 'SUCCEEDED'
                  AND j.fencing_token = NEW.fencing_token AND j.output_sha256 = NEW.output_sha256
                  AND j.staged_output_reference = NEW.staged_output_reference
                  AND e.worker_id = NEW.worker_id AND e.fencing_token = NEW.fencing_token
                  AND json_extract(e.details, '$.output_sha256') = NEW.output_sha256
                  AND w.status = 'ACTIVE' AND c.revoked_at IS NULL
                  AND julianday(c.expires_at) > julianday('now')
                  AND EXISTS (SELECT 1 FROM json_each(c.scopes) WHERE value = 'outputs:publish')
            )
            BEGIN SELECT RAISE(ABORT, 'publication requires successful fencing event and active scope'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_output_publication_no_update_0063
            BEFORE UPDATE ON dataset_execution_job_output_publications
            BEGIN SELECT RAISE(ABORT, 'dataset job output publication audit is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_output_publication_no_delete_0063
            BEFORE DELETE ON dataset_execution_job_output_publications
            BEGIN SELECT RAISE(ABORT, 'dataset job output publication audit is append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_output_publication_append_only_0063 ON dataset_execution_job_output_publications")
        op.execute("DROP FUNCTION IF EXISTS prevent_dataset_job_output_publication_mutation_0063()")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_output_publication_guard_0063 ON dataset_execution_job_output_publications")
        op.execute("DROP FUNCTION IF EXISTS enforce_dataset_job_output_publication_0063()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_output_publication_no_update_0063")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_output_publication_no_delete_0063")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_output_publication_guard_0063")
    op.drop_index("ix_dataset_job_output_publications_worker_created", table_name="dataset_execution_job_output_publications")
    op.drop_table("dataset_execution_job_output_publications")
