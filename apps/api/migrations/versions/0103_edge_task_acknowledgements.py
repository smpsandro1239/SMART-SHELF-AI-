"""Add append-only Edge task acknowledgement ledger."""

from alembic import op
import sqlalchemy as sa

revision = "0103_edge_task_acknowledgements"
down_revision = "0102_edge_task_assignments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_edge_task_assignment_ack_identity", "edge_device_task_assignments",
        ["id", "device_id", "task_id", "store_id", "task_version"], unique=True,
    )
    op.create_table(
        "edge_task_acknowledgements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("task_version", sa.Integer(), nullable=False),
        sa.Column("device_id", sa.String(length=120), nullable=False),
        sa.Column("assignment_id", sa.Integer(), sa.ForeignKey("edge_device_task_assignments.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("inbox_id", sa.Integer(), sa.ForeignKey("edge_device_event_inbox.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False),
        sa.Column("declared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("inbox_id", name="uq_edge_task_ack_inbox"),
        sa.UniqueConstraint("device_id", "event_id", name="uq_edge_task_ack_device_event"),
        sa.ForeignKeyConstraint(
            ["device_id", "event_id"], ["edge_device_event_inbox.device_id", "edge_device_event_inbox.event_id"],
            ondelete="RESTRICT", name="fk_edge_task_ack_inbox_identity",
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id", "device_id", "task_id", "store_id", "task_version"],
            ["edge_device_task_assignments.id", "edge_device_task_assignments.device_id",
             "edge_device_task_assignments.task_id", "edge_device_task_assignments.store_id",
             "edge_device_task_assignments.task_version"],
            ondelete="RESTRICT", name="fk_edge_task_ack_assignment_identity",
        ),
        sa.CheckConstraint("task_version > 0", name="ck_edge_task_ack_task_version"),
        sa.CheckConstraint("sequence_number > 0", name="ck_edge_task_ack_sequence"),
        sa.CheckConstraint("length(fingerprint_sha256) = 64", name="ck_edge_task_ack_fingerprint"),
        sa.CheckConstraint("action IN ('ACCEPTED', 'STARTED', 'COMPLETED')", name="ck_edge_task_ack_action"),
        sa.CheckConstraint("result IN ('ACCEPTED', 'STARTED', 'REVIEW_REQUIRED')", name="ck_edge_task_ack_result"),
    )
    op.create_index(
        "ix_edge_task_ack_store_task_created", "edge_task_acknowledgements",
        ["store_id", "task_id", "received_at"],
    )
    op.create_index(
        "ix_edge_task_ack_assignment_created", "edge_task_acknowledgements",
        ["assignment_id", "received_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION guard_edge_task_ack_immutability_0103()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'Edge task acknowledgements are append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_ack_immutable_0103
            BEFORE UPDATE OR DELETE ON edge_task_acknowledgements
            FOR EACH ROW EXECUTE FUNCTION guard_edge_task_ack_immutability_0103()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_edge_task_ack_update_guard_0103
            BEFORE UPDATE ON edge_task_acknowledgements
            BEGIN
                SELECT RAISE(ABORT, 'Edge task acknowledgements are append-only');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_edge_task_ack_delete_guard_0103
            BEFORE DELETE ON edge_task_acknowledgements
            BEGIN
                SELECT RAISE(ABORT, 'Edge task acknowledgements are append-only');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_edge_task_ack_immutable_0103 ON edge_task_acknowledgements")
        op.execute("DROP FUNCTION IF EXISTS guard_edge_task_ack_immutability_0103()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_edge_task_ack_delete_guard_0103")
        op.execute("DROP TRIGGER IF EXISTS trg_edge_task_ack_update_guard_0103")
    op.drop_index("ix_edge_task_ack_assignment_created", table_name="edge_task_acknowledgements")
    op.drop_index("ix_edge_task_ack_store_task_created", table_name="edge_task_acknowledgements")
    op.drop_table("edge_task_acknowledgements")
    op.drop_index("uq_edge_task_assignment_ack_identity", table_name="edge_device_task_assignments")
