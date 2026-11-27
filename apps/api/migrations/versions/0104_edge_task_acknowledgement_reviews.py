"""Add append-only human review ledger for Edge task acknowledgements."""
from alembic import op
import sqlalchemy as sa

revision = "0104_edge_task_acknowledgement_reviews"
down_revision = "0103_edge_task_acknowledgements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_edge_task_ack_id_store_task", "edge_task_acknowledgements",
        ["id", "store_id", "task_id"], unique=True,
    )
    op.create_table(
        "edge_task_acknowledgement_reviews",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("acknowledgement_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("decision", sa.String(length=8), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["acknowledgement_id", "store_id", "task_id"],
            ["edge_task_acknowledgements.id", "edge_task_acknowledgements.store_id", "edge_task_acknowledgements.task_id"],
            ondelete="RESTRICT", name="fk_edge_ack_review_ack_identity",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "store_id"], ["replenishment_tasks.id", "replenishment_tasks.store_id"],
            ondelete="RESTRICT", name="fk_edge_ack_review_task_identity",
        ),
        sa.UniqueConstraint(
            "store_id", "acknowledgement_id", "actor_user_id", "idempotency_key",
            name="uq_edge_ack_review_idempotency",
        ),
        sa.CheckConstraint("decision IN ('APPROVED', 'REJECTED')", name="ck_edge_ack_review_decision"),
        sa.CheckConstraint("length(reason) >= 3", name="ck_edge_ack_review_reason"),
        sa.CheckConstraint("length(evidence_reference) >= 1", name="ck_edge_ack_review_evidence"),
    )
    op.create_index(
        "ix_edge_ack_review_store_ack_time", "edge_task_acknowledgement_reviews",
        ["store_id", "acknowledgement_id", "reviewed_at"],
    )
    op.create_index(
        "ix_edge_ack_review_task_time", "edge_task_acknowledgement_reviews",
        ["task_id", "reviewed_at"],
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION guard_edge_task_ack_review_immutability_0104()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'Edge task acknowledgement reviews are append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_ack_review_immutable_0104
            BEFORE UPDATE OR DELETE ON edge_task_acknowledgement_reviews
            FOR EACH ROW EXECUTE FUNCTION guard_edge_task_ack_review_immutability_0104()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_edge_task_ack_review_update_guard_0104
            BEFORE UPDATE ON edge_task_acknowledgement_reviews
            BEGIN SELECT RAISE(ABORT, 'Edge task acknowledgement reviews are append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_ack_review_delete_guard_0104
            BEFORE DELETE ON edge_task_acknowledgement_reviews
            BEGIN SELECT RAISE(ABORT, 'Edge task acknowledgement reviews are append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_edge_task_ack_review_immutable_0104 ON edge_task_acknowledgement_reviews")
        op.execute("DROP FUNCTION IF EXISTS guard_edge_task_ack_review_immutability_0104()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_edge_task_ack_review_delete_guard_0104")
        op.execute("DROP TRIGGER IF EXISTS trg_edge_task_ack_review_update_guard_0104")
    op.drop_index("ix_edge_ack_review_task_time", table_name="edge_task_acknowledgement_reviews")
    op.drop_index("ix_edge_ack_review_store_ack_time", table_name="edge_task_acknowledgement_reviews")
    op.drop_table("edge_task_acknowledgement_reviews")
    op.drop_index("uq_edge_task_ack_id_store_task", table_name="edge_task_acknowledgements")
