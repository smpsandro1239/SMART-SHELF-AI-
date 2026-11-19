"""Immutable parent/derived lineage for published dataset outputs."""
from alembic import op
import sqlalchemy as sa

revision = "0066_dataset_output_lineage"
down_revision = "0065_dataset_output_governance_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_execution_job_output_lineage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("parent_publication_id", sa.Integer(), nullable=False),
        sa.Column("child_publication_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["parent_publication_id"], ["dataset_execution_job_output_publications.id"], name="fk_dataset_output_lineage_parent", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["child_publication_id"], ["dataset_execution_job_output_publications.id"], name="fk_dataset_output_lineage_child", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_dataset_output_lineage_actor", ondelete="RESTRICT"),
        sa.UniqueConstraint("parent_publication_id", "child_publication_id", name="uq_dataset_output_lineage_edge"),
        sa.CheckConstraint("parent_publication_id <> child_publication_id", name="ck_dataset_output_lineage_not_self"),
        sa.CheckConstraint("length(trim(reason)) > 0", name="ck_dataset_output_lineage_reason_nonempty"),
    )
    op.create_index("ix_dataset_output_lineage_child", "dataset_execution_job_output_lineage", ["child_publication_id", "parent_publication_id"])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION enforce_dataset_output_lineage_0066()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE cycle_found BOOLEAN; actor_active BOOLEAN;
            BEGIN
                PERFORM id FROM dataset_execution_job_output_publications
                WHERE id IN (NEW.parent_publication_id, NEW.child_publication_id)
                ORDER BY id FOR UPDATE;
                SELECT is_active INTO actor_active FROM users WHERE id = NEW.actor_user_id FOR SHARE;
                IF actor_active IS DISTINCT FROM TRUE THEN
                    RAISE EXCEPTION 'output lineage requires an active actor' USING ERRCODE = '23514';
                END IF;
                IF NEW.parent_publication_id = NEW.child_publication_id THEN
                    RAISE EXCEPTION 'output lineage cannot point to itself' USING ERRCODE = '23514';
                END IF;
                WITH RECURSIVE descendants(publication_id) AS (
                    SELECT child_publication_id FROM dataset_execution_job_output_lineage
                    WHERE parent_publication_id = NEW.child_publication_id
                    UNION
                    SELECT edge.child_publication_id FROM dataset_execution_job_output_lineage edge
                    JOIN descendants d ON edge.parent_publication_id = d.publication_id
                )
                SELECT EXISTS (SELECT 1 FROM descendants WHERE publication_id = NEW.parent_publication_id)
                INTO cycle_found;
                IF cycle_found THEN
                    RAISE EXCEPTION 'output lineage cycle is not permitted' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_output_lineage_guard_0066
            BEFORE INSERT ON dataset_execution_job_output_lineage
            FOR EACH ROW EXECUTE FUNCTION enforce_dataset_output_lineage_0066()
        """)
        op.execute("""
            CREATE FUNCTION prevent_dataset_output_lineage_mutation_0066()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'dataset output lineage is append-only' USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_output_lineage_append_only_0066
            BEFORE UPDATE OR DELETE ON dataset_execution_job_output_lineage
            FOR EACH ROW EXECUTE FUNCTION prevent_dataset_output_lineage_mutation_0066()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_output_lineage_guard_0066
            BEFORE INSERT ON dataset_execution_job_output_lineage
            BEGIN
                SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM dataset_execution_job_output_publications WHERE id = NEW.parent_publication_id)
                    OR NOT EXISTS (SELECT 1 FROM dataset_execution_job_output_publications WHERE id = NEW.child_publication_id)
                    THEN RAISE(ABORT, 'output lineage requires existing publications') END;
                SELECT CASE WHEN NOT EXISTS (SELECT 1 FROM users WHERE id = NEW.actor_user_id AND is_active = 1)
                    THEN RAISE(ABORT, 'output lineage requires an active actor') END;
                SELECT CASE WHEN NEW.parent_publication_id = NEW.child_publication_id
                    THEN RAISE(ABORT, 'output lineage cannot point to itself') END;
                SELECT CASE WHEN EXISTS (
                    WITH RECURSIVE descendants(publication_id) AS (
                        SELECT child_publication_id FROM dataset_execution_job_output_lineage
                        WHERE parent_publication_id = NEW.child_publication_id
                        UNION
                        SELECT edge.child_publication_id FROM dataset_execution_job_output_lineage edge
                        JOIN descendants d ON edge.parent_publication_id = d.publication_id
                    )
                    SELECT 1 FROM descendants WHERE publication_id = NEW.parent_publication_id
                ) THEN RAISE(ABORT, 'output lineage cycle is not permitted') END;
            END
        """)
        op.execute("CREATE TRIGGER trg_dataset_output_lineage_no_update_0066 BEFORE UPDATE ON dataset_execution_job_output_lineage BEGIN SELECT RAISE(ABORT, 'dataset output lineage is append-only'); END")
        op.execute("CREATE TRIGGER trg_dataset_output_lineage_no_delete_0066 BEFORE DELETE ON dataset_execution_job_output_lineage BEGIN SELECT RAISE(ABORT, 'dataset output lineage is append-only'); END")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_lineage_append_only_0066 ON dataset_execution_job_output_lineage")
        op.execute("DROP FUNCTION IF EXISTS prevent_dataset_output_lineage_mutation_0066()")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_lineage_guard_0066 ON dataset_execution_job_output_lineage")
        op.execute("DROP FUNCTION IF EXISTS enforce_dataset_output_lineage_0066()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_lineage_no_delete_0066")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_lineage_no_update_0066")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_output_lineage_guard_0066")
    op.drop_index("ix_dataset_output_lineage_child", table_name="dataset_execution_job_output_lineage")
    op.drop_table("dataset_execution_job_output_lineage")
