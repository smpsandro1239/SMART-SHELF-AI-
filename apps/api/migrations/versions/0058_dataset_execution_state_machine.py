"""Enforce the dataset execution job state machine and immutable identity."""

from alembic import op

revision = "0058_dataset_execution_state_machine"
down_revision = "0057_dataset_execution_fencing_guards"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION enforce_dataset_execution_state_machine_0058()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE now_utc TIMESTAMPTZ := clock_timestamp();
            BEGIN
                IF NEW.id IS DISTINCT FROM OLD.id
                   OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
                   OR NEW.request_sha256 IS DISTINCT FROM OLD.request_sha256
                   OR NEW.release_fingerprint IS DISTINCT FROM OLD.release_fingerprint
                   OR NEW.approval_record_sha256 IS DISTINCT FROM OLD.approval_record_sha256
                   OR NEW.approval_report_sha256 IS DISTINCT FROM OLD.approval_report_sha256
                   OR NEW.mode IS DISTINCT FROM OLD.mode
                   OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                    RAISE EXCEPTION 'dataset job identity is immutable' USING ERRCODE = '23514';
                END IF;

                IF OLD.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') THEN
                    RAISE EXCEPTION 'terminal dataset job is immutable' USING ERRCODE = '23514';
                END IF;

                IF OLD.status = 'QUEUED' THEN
                    IF NEW.status = 'LEASED' THEN
                        IF NEW.fencing_token <> OLD.fencing_token + 1
                           OR NEW.attempt_count <> OLD.attempt_count + 1
                           OR NEW.lease_owner IS NULL
                           OR NEW.lease_expires_at IS NULL
                           OR NEW.lease_expires_at <= now_utc THEN
                            RAISE EXCEPTION 'invalid initial dataset job claim' USING ERRCODE = '23514';
                        END IF;
                    ELSIF NEW.status IN ('REVOKED', 'CANCELLED') THEN
                        IF NEW.fencing_token <> OLD.fencing_token
                           OR NEW.attempt_count <> OLD.attempt_count
                           OR NEW.lease_owner IS NOT NULL
                           OR NEW.lease_expires_at IS NOT NULL
                           OR NEW.finished_at IS NULL THEN
                            RAISE EXCEPTION 'invalid queued dataset job termination' USING ERRCODE = '23514';
                        END IF;
                    ELSE
                        RAISE EXCEPTION 'invalid dataset job transition from QUEUED' USING ERRCODE = '23514';
                    END IF;
                ELSIF OLD.status = 'LEASED' THEN
                    IF NEW.status = 'LEASED' THEN
                        IF NEW.lease_owner IS NOT DISTINCT FROM OLD.lease_owner
                           AND NEW.fencing_token = OLD.fencing_token THEN
                            IF OLD.lease_expires_at <= now_utc
                               OR NEW.lease_expires_at IS NULL
                               OR NEW.lease_expires_at <= now_utc
                               OR NEW.lease_expires_at < OLD.lease_expires_at
                               OR NEW.attempt_count <> OLD.attempt_count THEN
                                RAISE EXCEPTION 'invalid dataset job heartbeat' USING ERRCODE = '23514';
                            END IF;
                        ELSE
                            IF OLD.lease_expires_at > now_utc
                               OR NEW.lease_owner IS NULL
                               OR NEW.lease_owner IS NOT DISTINCT FROM OLD.lease_owner
                               OR NEW.fencing_token <> OLD.fencing_token + 1
                               OR NEW.attempt_count <> OLD.attempt_count + 1
                               OR NEW.lease_expires_at IS NULL
                               OR NEW.lease_expires_at <= now_utc THEN
                                RAISE EXCEPTION 'invalid dataset job lease takeover' USING ERRCODE = '23514';
                            END IF;
                        END IF;
                    ELSIF NEW.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') THEN
                        IF NEW.fencing_token <> OLD.fencing_token
                           OR NEW.attempt_count <> OLD.attempt_count
                           OR NEW.lease_owner IS NOT NULL
                           OR NEW.lease_expires_at IS NOT NULL
                           OR NEW.finished_at IS NULL THEN
                            RAISE EXCEPTION 'invalid terminal dataset job transition' USING ERRCODE = '23514';
                        END IF;
                        IF NEW.status IN ('SUCCEEDED', 'FAILED')
                           AND OLD.lease_expires_at <= now_utc THEN
                            RAISE EXCEPTION 'expired dataset job lease cannot complete or fail' USING ERRCODE = '23514';
                        END IF;
                    ELSE
                        RAISE EXCEPTION 'invalid dataset job transition from LEASED' USING ERRCODE = '23514';
                    END IF;
                ELSE
                    RAISE EXCEPTION 'unknown prior dataset job state' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_state_machine_0058
            BEFORE UPDATE ON dataset_execution_jobs
            FOR EACH ROW EXECUTE FUNCTION enforce_dataset_execution_state_machine_0058()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_state_machine_0058
            BEFORE UPDATE ON dataset_execution_jobs
            WHEN
                NEW.id <> OLD.id
                OR NEW.idempotency_key <> OLD.idempotency_key
                OR NEW.request_sha256 <> OLD.request_sha256
                OR NEW.release_fingerprint <> OLD.release_fingerprint
                OR NEW.approval_record_sha256 <> OLD.approval_record_sha256
                OR NEW.approval_report_sha256 <> OLD.approval_report_sha256
                OR NEW.mode <> OLD.mode
                OR NEW.created_at <> OLD.created_at
                OR OLD.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')
                OR (
                    OLD.status = 'QUEUED'
                    AND NOT (
                        (NEW.status = 'LEASED'
                         AND NEW.fencing_token = OLD.fencing_token + 1
                         AND NEW.attempt_count = OLD.attempt_count + 1
                         AND NEW.lease_owner IS NOT NULL
                         AND NEW.lease_expires_at IS NOT NULL
                         AND julianday(NEW.lease_expires_at) > julianday('now'))
                        OR
                        (NEW.status IN ('REVOKED', 'CANCELLED')
                         AND NEW.fencing_token = OLD.fencing_token
                         AND NEW.attempt_count = OLD.attempt_count
                         AND NEW.lease_owner IS NULL
                         AND NEW.lease_expires_at IS NULL
                         AND NEW.finished_at IS NOT NULL)
                    )
                )
                OR (
                    OLD.status = 'LEASED'
                    AND NOT (
                        (NEW.status = 'LEASED'
                         AND NEW.lease_owner = OLD.lease_owner
                         AND NEW.fencing_token = OLD.fencing_token
                         AND NEW.attempt_count = OLD.attempt_count
                         AND julianday(OLD.lease_expires_at) > julianday('now')
                         AND julianday(NEW.lease_expires_at) > julianday('now')
                         AND julianday(NEW.lease_expires_at) >= julianday(OLD.lease_expires_at))
                        OR
                        (NEW.status = 'LEASED'
                         AND NEW.lease_owner IS NOT OLD.lease_owner
                         AND NEW.fencing_token = OLD.fencing_token + 1
                         AND NEW.attempt_count = OLD.attempt_count + 1
                         AND julianday(OLD.lease_expires_at) <= julianday('now')
                         AND NEW.lease_owner IS NOT NULL
                         AND julianday(NEW.lease_expires_at) > julianday('now'))
                        OR
                        (NEW.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')
                         AND NEW.fencing_token = OLD.fencing_token
                         AND NEW.attempt_count = OLD.attempt_count
                         AND NEW.lease_owner IS NULL
                         AND NEW.lease_expires_at IS NULL
                         AND NEW.finished_at IS NOT NULL
                         AND (NEW.status IN ('REVOKED', 'CANCELLED')
                              OR julianday(OLD.lease_expires_at) > julianday('now')))
                    )
                )
            BEGIN SELECT RAISE(ABORT, 'invalid dataset job state transition or immutable identity'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_execution_state_machine_0058 ON dataset_execution_jobs")
        op.execute("DROP FUNCTION IF EXISTS enforce_dataset_execution_state_machine_0058()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_execution_state_machine_0058")
