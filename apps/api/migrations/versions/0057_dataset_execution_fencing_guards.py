"""Add database-enforced fencing transitions and contiguous job event sequences."""

from alembic import op

revision = "0057_dataset_execution_fencing_guards"
down_revision = "0056_dataset_execution_job_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_dataset_execution_job_success_output",
            "dataset_execution_jobs",
            "status <> 'SUCCEEDED' OR (output_sha256 IS NOT NULL AND staged_output_reference IS NOT NULL)",
        )
        op.create_check_constraint(
            "ck_dataset_execution_job_finished_state",
            "dataset_execution_jobs",
            "(status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') AND finished_at IS NOT NULL) OR (status NOT IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') AND finished_at IS NULL)",
        )
        op.create_check_constraint(
            "ck_dataset_execution_job_active_fencing",
            "dataset_execution_jobs",
            "status <> 'LEASED' OR (fencing_token > 0 AND attempt_count > 0)",
        )
        op.execute("""
            CREATE OR REPLACE FUNCTION enforce_dataset_execution_fencing_0057()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE now_utc TIMESTAMPTZ := clock_timestamp();
            BEGIN
                IF NEW.status = 'LEASED' THEN
                    IF NEW.lease_expires_at IS NULL OR NEW.lease_expires_at <= now_utc THEN
                        RAISE EXCEPTION 'dataset job lease must expire in the future' USING ERRCODE = '23514';
                    END IF;
                    IF OLD.status = 'QUEUED' THEN
                        IF NEW.fencing_token <> OLD.fencing_token + 1
                           OR NEW.attempt_count <> OLD.attempt_count + 1 THEN
                            RAISE EXCEPTION 'initial claim must increment fencing token and attempt count' USING ERRCODE = '23514';
                        END IF;
                    ELSIF OLD.status = 'LEASED' THEN
                        IF NEW.lease_owner IS NOT DISTINCT FROM OLD.lease_owner
                           AND NEW.fencing_token = OLD.fencing_token THEN
                            IF OLD.lease_expires_at <= now_utc
                               OR NEW.lease_expires_at < OLD.lease_expires_at
                               OR NEW.attempt_count <> OLD.attempt_count THEN
                                RAISE EXCEPTION 'heartbeat cannot renew an expired lease or shorten its expiry' USING ERRCODE = '23514';
                            END IF;
                        ELSE
                            IF OLD.lease_expires_at > now_utc
                               OR NEW.fencing_token <> OLD.fencing_token + 1
                               OR NEW.attempt_count <> OLD.attempt_count + 1 THEN
                                RAISE EXCEPTION 'takeover requires an expired lease and the next fencing token' USING ERRCODE = '23514';
                            END IF;
                        END IF;
                    END IF;
                ELSIF NEW.status IN ('SUCCEEDED', 'FAILED') THEN
                    IF OLD.status <> 'LEASED' OR OLD.lease_expires_at <= now_utc THEN
                        RAISE EXCEPTION 'only the current unexpired lease can complete or fail a job' USING ERRCODE = '23514';
                    END IF;
                    IF NEW.fencing_token <> OLD.fencing_token
                       OR NEW.attempt_count <> OLD.attempt_count THEN
                        RAISE EXCEPTION 'terminal transition cannot change fencing counters' USING ERRCODE = '23514';
                    END IF;
                ELSE
                    IF NEW.fencing_token <> OLD.fencing_token
                       OR NEW.attempt_count <> OLD.attempt_count THEN
                        RAISE EXCEPTION 'revocation or cancellation cannot change fencing counters' USING ERRCODE = '23514';
                    END IF;
                END IF;
                IF NEW.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')
                   AND NEW.finished_at IS NULL THEN
                    RAISE EXCEPTION 'terminal dataset job requires finished_at' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_fencing_0057
            BEFORE UPDATE ON dataset_execution_jobs
            FOR EACH ROW EXECUTE FUNCTION enforce_dataset_execution_fencing_0057()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION enforce_dataset_job_event_sequence_0057()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE expected_sequence INTEGER;
                    job_status VARCHAR(16);
            BEGIN
                SELECT status INTO job_status
                FROM dataset_execution_jobs
                WHERE id = NEW.job_id
                FOR UPDATE;
                IF NOT FOUND THEN
                    RAISE EXCEPTION 'dataset job event references an unknown job' USING ERRCODE = '23503';
                END IF;
                IF job_status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')
                   AND (NEW.event_type <> job_status OR EXISTS (
                       SELECT 1 FROM dataset_execution_job_events
                       WHERE job_id = NEW.job_id AND event_type = job_status
                   )) THEN
                    RAISE EXCEPTION 'terminal dataset job cannot receive further events' USING ERRCODE = '23514';
                END IF;
                SELECT COALESCE(MAX(sequence_number), 0) + 1
                INTO expected_sequence
                FROM dataset_execution_job_events
                WHERE job_id = NEW.job_id;
                IF NEW.sequence_number <> expected_sequence THEN
                    RAISE EXCEPTION 'dataset job event sequence must be contiguous' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_event_sequence_0057
            BEFORE INSERT ON dataset_execution_job_events
            FOR EACH ROW EXECUTE FUNCTION enforce_dataset_job_event_sequence_0057()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_success_output_0057
            BEFORE INSERT ON dataset_execution_jobs
            WHEN NEW.status = 'SUCCEEDED'
             AND (NEW.output_sha256 IS NULL OR NEW.staged_output_reference IS NULL)
            BEGIN SELECT RAISE(ABORT, 'successful dataset job requires staged output digest and reference'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_success_output_update_0057
            BEFORE UPDATE ON dataset_execution_jobs
            WHEN NEW.status = 'SUCCEEDED'
             AND (NEW.output_sha256 IS NULL OR NEW.staged_output_reference IS NULL)
            BEGIN SELECT RAISE(ABORT, 'successful dataset job requires staged output digest and reference'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_finished_state_0057
            BEFORE INSERT ON dataset_execution_jobs
            WHEN (NEW.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') AND NEW.finished_at IS NULL)
              OR (NEW.status NOT IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') AND NEW.finished_at IS NOT NULL)
              OR (NEW.status = 'LEASED' AND (NEW.fencing_token <= 0 OR NEW.attempt_count <= 0))
            BEGIN SELECT RAISE(ABORT, 'invalid dataset job terminal or fencing state'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_finished_state_update_0057
            BEFORE UPDATE ON dataset_execution_jobs
            WHEN (NEW.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') AND NEW.finished_at IS NULL)
              OR (NEW.status NOT IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') AND NEW.finished_at IS NOT NULL)
              OR (NEW.status = 'LEASED' AND (NEW.fencing_token <= 0 OR NEW.attempt_count <= 0))
            BEGIN SELECT RAISE(ABORT, 'invalid dataset job terminal or fencing state'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_fencing_0057
            BEFORE UPDATE ON dataset_execution_jobs
            WHEN (
                NEW.status = 'LEASED' AND OLD.status = 'QUEUED'
                AND (NEW.fencing_token <> OLD.fencing_token + 1
                     OR NEW.attempt_count <> OLD.attempt_count + 1
                     OR julianday(NEW.lease_expires_at) <= julianday('now'))
            ) OR (
                NEW.status = 'LEASED' AND OLD.status = 'LEASED'
                AND NEW.lease_owner IS OLD.lease_owner
                AND NEW.fencing_token = OLD.fencing_token
                AND (julianday(OLD.lease_expires_at) <= julianday('now')
                     OR julianday(NEW.lease_expires_at) < julianday(OLD.lease_expires_at)
                     OR NEW.attempt_count <> OLD.attempt_count)
            ) OR (
                NEW.status = 'LEASED' AND OLD.status = 'LEASED'
                AND (NEW.lease_owner IS NOT OLD.lease_owner OR NEW.fencing_token <> OLD.fencing_token)
                AND (julianday(OLD.lease_expires_at) > julianday('now')
                     OR NEW.fencing_token <> OLD.fencing_token + 1
                     OR NEW.attempt_count <> OLD.attempt_count + 1
                     OR julianday(NEW.lease_expires_at) <= julianday('now'))
            ) OR (
                NEW.status IN ('SUCCEEDED', 'FAILED')
                AND (OLD.status <> 'LEASED' OR julianday(OLD.lease_expires_at) <= julianday('now')
                     OR NEW.fencing_token <> OLD.fencing_token
                     OR NEW.attempt_count <> OLD.attempt_count)
            ) OR (
                NEW.status IN ('REVOKED', 'CANCELLED')
                AND (NEW.fencing_token <> OLD.fencing_token
                     OR NEW.attempt_count <> OLD.attempt_count)
            )
            BEGIN SELECT RAISE(ABORT, 'invalid dataset job fencing or lease transition'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_job_event_sequence_0057
            BEFORE INSERT ON dataset_execution_job_events
            WHEN NEW.sequence_number <> (
                SELECT COALESCE(MAX(sequence_number), 0) + 1
                FROM dataset_execution_job_events WHERE job_id = NEW.job_id
            ) OR EXISTS (
                SELECT 1 FROM dataset_execution_jobs j
                WHERE j.id = NEW.job_id
                  AND j.status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')
                  AND (NEW.event_type <> j.status OR EXISTS (
                      SELECT 1 FROM dataset_execution_job_events e
                      WHERE e.job_id = NEW.job_id AND e.event_type = j.status
                  ))
            )
            BEGIN SELECT RAISE(ABORT, 'invalid dataset job event sequence or terminal event'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_execution_fencing_0057 ON dataset_execution_jobs")
        op.execute("DROP FUNCTION IF EXISTS enforce_dataset_execution_fencing_0057()")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_job_event_sequence_0057 ON dataset_execution_job_events")
        op.execute("DROP FUNCTION IF EXISTS enforce_dataset_job_event_sequence_0057()")
        op.drop_constraint("ck_dataset_execution_job_active_fencing", "dataset_execution_jobs", type_="check")
        op.drop_constraint("ck_dataset_execution_job_finished_state", "dataset_execution_jobs", type_="check")
        op.drop_constraint("ck_dataset_execution_job_success_output", "dataset_execution_jobs", type_="check")
    elif bind.dialect.name == "sqlite":
        for name in (
            "trg_dataset_execution_success_output_0057",
            "trg_dataset_execution_success_output_update_0057",
            "trg_dataset_execution_finished_state_0057",
            "trg_dataset_execution_finished_state_update_0057",
            "trg_dataset_execution_fencing_0057",
            "trg_dataset_job_event_sequence_0057",
        ):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
