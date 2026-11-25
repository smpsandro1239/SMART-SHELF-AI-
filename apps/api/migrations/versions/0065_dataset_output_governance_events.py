"""Append-only governance events for published dataset outputs."""
from alembic import op
import sqlalchemy as sa

revision = "0065_dataset_output_governance_events"
down_revision = "0064_dataset_output_source_eligibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_execution_job_output_governance_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(length=600), nullable=True),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["publication_id"], ["dataset_execution_job_output_publications.id"], name="fk_dataset_output_governance_publication", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_dataset_output_governance_actor", ondelete="RESTRICT"),
        sa.UniqueConstraint("publication_id", "sequence_number", name="uq_dataset_output_governance_publication_sequence"),
        sa.CheckConstraint("sequence_number > 0", name="ck_dataset_output_governance_sequence_positive"),
        sa.CheckConstraint("event_type IN ('RESTRICTION_APPLIED', 'RESTRICTION_RELEASED', 'LEGAL_HOLD_APPLIED', 'LEGAL_HOLD_RELEASED')", name="ck_dataset_output_governance_event_type"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_dataset_output_governance_reason_nonempty"),
        sa.CheckConstraint("(evidence_reference IS NULL AND evidence_sha256 IS NULL) OR (evidence_reference IS NOT NULL AND length(evidence_reference) > 0 AND evidence_sha256 IS NOT NULL AND length(evidence_sha256) = 64)", name="ck_dataset_output_governance_evidence_pair"),
    )
    op.create_index("ix_dataset_output_governance_publication_sequence", "dataset_execution_job_output_governance_events", ["publication_id", "sequence_number"])
    op.create_index("ix_dataset_output_governance_actor_created", "dataset_execution_job_output_governance_events", ["actor_user_id", "created_at"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION enforce_dataset_output_governance_event_0065()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE expected_sequence INTEGER; last_restriction TEXT; last_hold TEXT;
            BEGIN
                PERFORM id FROM dataset_execution_job_output_publications WHERE id = NEW.publication_id FOR UPDATE;
                IF NOT FOUND THEN RAISE EXCEPTION 'output governance requires an existing publication' USING ERRCODE = '23503'; END IF;
                PERFORM id FROM users WHERE id = NEW.actor_user_id AND is_active IS TRUE FOR SHARE;
                IF NOT FOUND THEN RAISE EXCEPTION 'output governance requires an active human actor' USING ERRCODE = '23514'; END IF;
                SELECT COALESCE(MAX(sequence_number), 0) + 1 INTO expected_sequence
                FROM dataset_execution_job_output_governance_events WHERE publication_id = NEW.publication_id;
                IF NEW.sequence_number <> expected_sequence THEN RAISE EXCEPTION 'output governance sequence must be consecutive' USING ERRCODE = '23514'; END IF;
                SELECT event_type INTO last_restriction FROM dataset_execution_job_output_governance_events
                WHERE publication_id = NEW.publication_id AND event_type IN ('RESTRICTION_APPLIED', 'RESTRICTION_RELEASED')
                ORDER BY sequence_number DESC LIMIT 1;
                SELECT event_type INTO last_hold FROM dataset_execution_job_output_governance_events
                WHERE publication_id = NEW.publication_id AND event_type IN ('LEGAL_HOLD_APPLIED', 'LEGAL_HOLD_RELEASED')
                ORDER BY sequence_number DESC LIMIT 1;
                IF NEW.event_type = 'RESTRICTION_APPLIED' AND last_restriction = 'RESTRICTION_APPLIED' THEN
                    RAISE EXCEPTION 'output restriction is already active' USING ERRCODE = '23514';
                ELSIF NEW.event_type = 'RESTRICTION_RELEASED' AND last_restriction IS DISTINCT FROM 'RESTRICTION_APPLIED' THEN
                    RAISE EXCEPTION 'output restriction is not active' USING ERRCODE = '23514';
                ELSIF NEW.event_type = 'LEGAL_HOLD_APPLIED' AND last_hold = 'LEGAL_HOLD_APPLIED' THEN
                    RAISE EXCEPTION 'output legal hold is already active' USING ERRCODE = '23514';
                ELSIF NEW.event_type = 'LEGAL_HOLD_RELEASED' AND last_hold IS DISTINCT FROM 'LEGAL_HOLD_APPLIED' THEN
                    RAISE EXCEPTION 'output legal hold is not active' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_output_governance_event_guard_0065
            BEFORE INSERT ON dataset_execution_job_output_governance_events
            FOR EACH ROW EXECUTE FUNCTION enforce_dataset_output_governance_event_0065()
        """)
        op.execute("""
            CREATE FUNCTION prevent_dataset_output_governance_event_mutation_0065()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'dataset output governance events are append-only' USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_output_governance_event_append_only_0065
            BEFORE UPDATE OR DELETE ON dataset_execution_job_output_governance_events
            FOR EACH ROW EXECUTE FUNCTION prevent_dataset_output_governance_event_mutation_0065()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_output_governance_event_guard_0065
            BEFORE INSERT ON dataset_execution_job_output_governance_events
            BEGIN
                SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM dataset_execution_job_output_publications WHERE id = NEW.publication_id)
                    THEN RAISE(ABORT, 'output governance requires an existing publication') END;
                SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.actor_user_id AND is_active = 1)
                    THEN RAISE(ABORT, 'output governance requires an active human actor') END;
                SELECT CASE WHEN NEW.sequence_number <> (SELECT COALESCE(MAX(sequence_number), 0) + 1 FROM dataset_execution_job_output_governance_events WHERE publication_id = NEW.publication_id)
                    THEN RAISE(ABORT, 'output governance sequence must be consecutive') END;
                SELECT CASE WHEN NEW.event_type = 'RESTRICTION_APPLIED'
                    AND (SELECT event_type FROM dataset_execution_job_output_governance_events WHERE publication_id = NEW.publication_id AND event_type IN ('RESTRICTION_APPLIED', 'RESTRICTION_RELEASED') ORDER BY sequence_number DESC LIMIT 1) = 'RESTRICTION_APPLIED'
                    THEN RAISE(ABORT, 'output restriction is already active') END;
                SELECT CASE WHEN NEW.event_type = 'RESTRICTION_RELEASED'
                    AND COALESCE((SELECT event_type FROM dataset_execution_job_output_governance_events WHERE publication_id = NEW.publication_id AND event_type IN ('RESTRICTION_APPLIED', 'RESTRICTION_RELEASED') ORDER BY sequence_number DESC LIMIT 1), '') <> 'RESTRICTION_APPLIED'
                    THEN RAISE(ABORT, 'output restriction is not active') END;
                SELECT CASE WHEN NEW.event_type = 'LEGAL_HOLD_APPLIED'
                    AND (SELECT event_type FROM dataset_execution_job_output_governance_events WHERE publication_id = NEW.publication_id AND event_type IN ('LEGAL_HOLD_APPLIED', 'LEGAL_HOLD_RELEASED') ORDER BY sequence_number DESC LIMIT 1) = 'LEGAL_HOLD_APPLIED'
                    THEN RAISE(ABORT, 'output legal hold is already active') END;
                SELECT CASE WHEN NEW.event_type = 'LEGAL_HOLD_RELEASED'
                    AND COALESCE((SELECT event_type FROM dataset_execution_job_output_governance_events WHERE publication_id = NEW.publication_id AND event_type IN ('LEGAL_HOLD_APPLIED', 'LEGAL_HOLD_RELEASED') ORDER BY sequence_number DESC LIMIT 1), '') <> 'LEGAL_HOLD_APPLIED'
                    THEN RAISE(ABORT, 'output legal hold is not active') END;
            END
        """)
        op.execute("CREATE TRIGGER trg_dataset_output_governance_event_no_update_0065 BEFORE UPDATE ON dataset_execution_job_output_governance_events BEGIN SELECT RAISE(ABORT, 'dataset output governance events are append-only'); END")
        op.execute("CREATE TRIGGER trg_dataset_output_governance_event_no_delete_0065 BEFORE DELETE ON dataset_execution_job_output_governance_events BEGIN SELECT RAISE(ABORT, 'dataset output governance events are append-only'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_governance_event_append_only_0065 ON dataset_execution_job_output_governance_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_dataset_output_governance_event_mutation_0065()")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_governance_event_guard_0065 ON dataset_execution_job_output_governance_events")
        op.execute("DROP FUNCTION IF EXISTS enforce_dataset_output_governance_event_0065()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_governance_event_no_update_0065")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_governance_event_no_delete_0065")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_governance_event_guard_0065")
    op.drop_index("ix_dataset_output_governance_actor_created", table_name="dataset_execution_job_output_governance_events")
    op.drop_index("ix_dataset_output_governance_publication_sequence", table_name="dataset_execution_job_output_governance_events")
    op.drop_table("dataset_execution_job_output_governance_events")
