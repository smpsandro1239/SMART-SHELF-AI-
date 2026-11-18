"""Add durable dataset execution jobs, immutable sources and fenced leases."""

import sqlalchemy as sa
from alembic import op

revision = "0056_dataset_execution_job_leases"
down_revision = "0055_pallet_rotation_events_append_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_execution_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("release_fingerprint", sa.String(64), nullable=False),
        sa.Column("approval_record_sha256", sa.String(64), nullable=False),
        sa.Column("approval_report_sha256", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="QUEUED"),
        sa.Column("lease_owner", sa.String(160)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("fencing_token", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_sha256", sa.String(64)),
        sa.Column("staged_output_reference", sa.String(600)),
        sa.Column("failure_code", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("idempotency_key", name="uq_dataset_execution_job_idempotency"),
        sa.CheckConstraint("status IN ('QUEUED', 'LEASED', 'SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')", name="ck_dataset_execution_job_status"),
        sa.CheckConstraint("mode IN ('training', 'inference')", name="ck_dataset_execution_job_mode"),
        sa.CheckConstraint("length(release_fingerprint) = 64", name="ck_dataset_execution_job_release_digest"),
        sa.CheckConstraint("length(approval_record_sha256) = 64", name="ck_dataset_execution_job_record_digest"),
        sa.CheckConstraint("length(approval_report_sha256) = 64", name="ck_dataset_execution_job_report_digest"),
        sa.CheckConstraint("length(request_sha256) = 64", name="ck_dataset_execution_job_request_digest"),
        sa.CheckConstraint("fencing_token >= 0", name="ck_dataset_execution_job_fencing_nonnegative"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_dataset_execution_job_attempts_nonnegative"),
        sa.CheckConstraint("(status = 'LEASED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'LEASED' AND lease_owner IS NULL AND lease_expires_at IS NULL)", name="ck_dataset_execution_job_lease_state"),
        sa.CheckConstraint("output_sha256 IS NULL OR length(output_sha256) = 64", name="ck_dataset_execution_job_output_digest"),
    )
    op.create_index("ix_dataset_execution_jobs_claim", "dataset_execution_jobs", ["status", "lease_expires_at", "created_at", "id"])
    op.create_table(
        "dataset_execution_job_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("shelf_image_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("source_image_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["job_id"], ["dataset_execution_jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["shelf_image_id"], ["shelf_images.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("job_id", "shelf_image_id", name="uq_dataset_execution_job_source"),
        sa.CheckConstraint("length(source_image_sha256) = 64", name="ck_dataset_execution_source_digest"),
    )
    op.create_index("ix_dataset_execution_job_sources_job_id", "dataset_execution_job_sources", ["job_id"])
    op.create_index("ix_dataset_execution_job_sources_shelf_image_id", "dataset_execution_job_sources", ["shelf_image_id"])
    op.create_index("ix_dataset_execution_job_sources_store_id", "dataset_execution_job_sources", ["store_id"])
    op.create_index("ix_dataset_execution_job_sources_image", "dataset_execution_job_sources", ["shelf_image_id", "job_id"])
    op.create_table(
        "dataset_execution_job_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("worker_id", sa.String(160)),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["job_id"], ["dataset_execution_jobs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("job_id", "sequence_number", name="uq_dataset_execution_job_event_sequence"),
        sa.CheckConstraint("event_type IN ('QUEUED', 'CLAIMED', 'HEARTBEAT', 'SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')", name="ck_dataset_execution_job_event_type"),
        sa.CheckConstraint("fencing_token >= 0", name="ck_dataset_execution_job_event_fencing_nonnegative"),
    )
    op.create_index("ix_dataset_execution_job_events_job_id", "dataset_execution_job_events", ["job_id"])
    op.create_index("ix_dataset_execution_job_events_job_sequence", "dataset_execution_job_events", ["job_id", "sequence_number"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION guard_dataset_execution_job_0056()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'dataset execution jobs cannot be deleted' USING ERRCODE = '23514';
                END IF;
                IF NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                   OR NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256
                   OR NEW.release_fingerprint IS DISTINCT FROM OLD.release_fingerprint
                   OR NEW.approval_record_sha256 IS DISTINCT FROM OLD.approval_record_sha256
                   OR NEW.approval_report_sha256 IS DISTINCT FROM OLD.approval_report_sha256
                   OR NEW.mode IS DISTINCT FROM OLD.mode
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'dataset execution job identity is immutable' USING ERRCODE = '23514';
                END IF;
                IF OLD.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') THEN
                    RAISE EXCEPTION 'terminal dataset execution job is immutable' USING ERRCODE = '23514';
                END IF;
                IF NEW.fencing_token < OLD.fencing_token OR NEW.attempt_count < OLD.attempt_count THEN
                    RAISE EXCEPTION 'dataset execution fencing counters cannot decrease' USING ERRCODE = '23514';
                END IF;
                IF OLD.status = 'QUEUED' AND NEW.status NOT IN ('QUEUED', 'LEASED', 'REVOKED', 'CANCELLED') THEN
                    RAISE EXCEPTION 'invalid dataset execution job transition' USING ERRCODE = '23514';
                END IF;
                IF OLD.status = 'LEASED' AND NEW.status NOT IN ('LEASED', 'SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') THEN
                    RAISE EXCEPTION 'invalid dataset execution job transition' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_job_guard_0056
            BEFORE UPDATE OR DELETE ON dataset_execution_jobs
            FOR EACH ROW EXECUTE FUNCTION guard_dataset_execution_job_0056()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION guard_dataset_execution_source_0056()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE actual_store_id INTEGER; actual_sha256 VARCHAR(64);
                    actual_status VARCHAR(20); actual_legal_hold BOOLEAN;
            BEGIN
                IF TG_OP IN ('UPDATE', 'DELETE') THEN
                    RAISE EXCEPTION 'dataset execution job sources are immutable' USING ERRCODE = '23514';
                END IF;
                SELECT z.store_id, si.sha256, si.retention_status, si.legal_hold
                INTO actual_store_id, actual_sha256, actual_status, actual_legal_hold
                FROM shelf_images si JOIN shelves sh ON sh.id = si.shelf_id
                JOIN zones z ON z.id = sh.zone_id
                WHERE si.id = NEW.shelf_image_id
                FOR UPDATE OF si, sh, z;
                IF NOT FOUND OR actual_store_id <> NEW.store_id
                   OR actual_sha256 <> NEW.source_image_sha256
                   OR actual_status <> 'ACTIVE' OR actual_legal_hold IS TRUE THEN
                    RAISE EXCEPTION 'dataset execution source is not operationally eligible' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_source_guard_0056
            BEFORE INSERT OR UPDATE OR DELETE ON dataset_execution_job_sources
            FOR EACH ROW EXECUTE FUNCTION guard_dataset_execution_source_0056()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_dataset_execution_job_event_mutation_0056()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'dataset execution job events are append-only' USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_job_events_append_only
            BEFORE UPDATE OR DELETE ON dataset_execution_job_events
            FOR EACH ROW EXECUTE FUNCTION prevent_dataset_execution_job_event_mutation_0056()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_job_no_delete_0056 BEFORE DELETE ON dataset_execution_jobs
            BEGIN SELECT RAISE(ABORT, 'dataset execution jobs cannot be deleted'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_job_guard_0056 BEFORE UPDATE ON dataset_execution_jobs
            WHEN NEW.idempotency_key <> OLD.idempotency_key
              OR NEW.request_sha256 <> OLD.request_sha256
              OR NEW.release_fingerprint <> OLD.release_fingerprint
              OR NEW.approval_record_sha256 <> OLD.approval_record_sha256
              OR NEW.approval_report_sha256 <> OLD.approval_report_sha256
              OR NEW.mode <> OLD.mode OR NEW.created_at <> OLD.created_at
              OR NEW.fencing_token < OLD.fencing_token OR NEW.attempt_count < OLD.attempt_count
              OR OLD.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')
              OR (OLD.status = 'QUEUED' AND NEW.status NOT IN ('QUEUED', 'LEASED', 'REVOKED', 'CANCELLED'))
              OR (OLD.status = 'LEASED' AND NEW.status NOT IN ('LEASED', 'SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED'))
            BEGIN SELECT RAISE(ABORT, 'invalid or immutable dataset execution job update'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_source_validate_0056 BEFORE INSERT ON dataset_execution_job_sources
            WHEN NOT EXISTS (
                SELECT 1 FROM shelf_images si JOIN shelves sh ON sh.id = si.shelf_id
                JOIN zones z ON z.id = sh.zone_id
                WHERE si.id = NEW.shelf_image_id AND z.store_id = NEW.store_id
                  AND si.sha256 = NEW.source_image_sha256
                  AND si.retention_status = 'ACTIVE' AND si.legal_hold = 0
            )
            BEGIN SELECT RAISE(ABORT, 'dataset execution source is not operationally eligible'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_source_no_update_0056 BEFORE UPDATE ON dataset_execution_job_sources
            BEGIN SELECT RAISE(ABORT, 'dataset execution job sources are immutable'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_source_no_delete_0056 BEFORE DELETE ON dataset_execution_job_sources
            BEGIN SELECT RAISE(ABORT, 'dataset execution job sources are immutable'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_job_events_no_update_0056 BEFORE UPDATE ON dataset_execution_job_events
            BEGIN SELECT RAISE(ABORT, 'dataset execution job events are append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_job_events_no_delete_0056 BEFORE DELETE ON dataset_execution_job_events
            BEGIN SELECT RAISE(ABORT, 'dataset execution job events are append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_execution_job_guard_0056 ON dataset_execution_jobs")
        op.execute("DROP FUNCTION IF EXISTS guard_dataset_execution_job_0056()")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_execution_source_guard_0056 ON dataset_execution_job_sources")
        op.execute("DROP FUNCTION IF EXISTS guard_dataset_execution_source_0056()")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_execution_job_events_append_only ON dataset_execution_job_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_dataset_execution_job_event_mutation_0056()")
    elif bind.dialect.name == "sqlite":
        for name in (
            "trg_dataset_execution_job_no_delete_0056", "trg_dataset_execution_job_guard_0056",
            "trg_dataset_execution_source_validate_0056", "trg_dataset_execution_source_no_update_0056",
            "trg_dataset_execution_source_no_delete_0056", "trg_dataset_execution_job_events_no_update_0056",
            "trg_dataset_execution_job_events_no_delete_0056",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_index("ix_dataset_execution_job_events_job_sequence", table_name="dataset_execution_job_events")
    op.drop_index("ix_dataset_execution_job_events_job_id", table_name="dataset_execution_job_events")
    op.drop_table("dataset_execution_job_events")
    op.drop_index("ix_dataset_execution_job_sources_image", table_name="dataset_execution_job_sources")
    op.drop_index("ix_dataset_execution_job_sources_store_id", table_name="dataset_execution_job_sources")
    op.drop_index("ix_dataset_execution_job_sources_shelf_image_id", table_name="dataset_execution_job_sources")
    op.drop_index("ix_dataset_execution_job_sources_job_id", table_name="dataset_execution_job_sources")
    op.drop_table("dataset_execution_job_sources")
    op.drop_index("ix_dataset_execution_jobs_claim", table_name="dataset_execution_jobs")
    op.drop_table("dataset_execution_jobs")
