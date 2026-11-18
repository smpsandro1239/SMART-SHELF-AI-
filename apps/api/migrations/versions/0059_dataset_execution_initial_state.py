"""Require every dataset execution job to enter through the queued state."""

from alembic import op

revision = "0059_dataset_execution_initial_state"
down_revision = "0058_dataset_execution_state_machine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION enforce_dataset_execution_initial_state_0059()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                IF NEW.status <> 'QUEUED'
                   OR NEW.lease_owner IS NOT NULL
                   OR NEW.lease_expires_at IS NOT NULL
                   OR NEW.fencing_token <> 0
                   OR NEW.attempt_count <> 0
                   OR NEW.output_sha256 IS NOT NULL
                   OR NEW.staged_output_reference IS NOT NULL
                   OR NEW.failure_code IS NOT NULL
                   OR NEW.finished_at IS NOT NULL THEN
                    RAISE EXCEPTION 'dataset execution jobs must be inserted in the initial QUEUED state'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_initial_state_0059
            BEFORE INSERT ON dataset_execution_jobs
            FOR EACH ROW EXECUTE FUNCTION enforce_dataset_execution_initial_state_0059()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_execution_initial_state_0059
            BEFORE INSERT ON dataset_execution_jobs
            WHEN NEW.status <> 'QUEUED'
              OR NEW.lease_owner IS NOT NULL
              OR NEW.lease_expires_at IS NOT NULL
              OR NEW.fencing_token <> 0
              OR NEW.attempt_count <> 0
              OR NEW.output_sha256 IS NOT NULL
              OR NEW.staged_output_reference IS NOT NULL
              OR NEW.failure_code IS NOT NULL
              OR NEW.finished_at IS NOT NULL
            BEGIN
                SELECT RAISE(ABORT, 'dataset execution jobs must be inserted in the initial QUEUED state');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_execution_initial_state_0059 ON dataset_execution_jobs")
        op.execute("DROP FUNCTION IF EXISTS enforce_dataset_execution_initial_state_0059()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_execution_initial_state_0059")
