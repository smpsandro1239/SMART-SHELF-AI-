"""Add individually managed credentials for dataset execution workers."""

from alembic import op
import sqlalchemy as sa

revision = "0060_dataset_worker_credentials"
down_revision = "0059_dataset_execution_initial_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_workers",
        sa.Column("worker_id", sa.String(length=160), primary_key=True, nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_dataset_worker_status"),
    )
    op.create_index(
        "ix_dataset_workers_status_created", "dataset_workers", ["status", "created_at"]
    )

    op.create_table(
        "dataset_worker_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("credential_id", sa.String(length=32), nullable=False),
        sa.Column("worker_id", sa.String(length=160), nullable=False),
        sa.Column("secret_sha256", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_credential_id", sa.String(length=32), nullable=True),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["dataset_workers.worker_id"],
            name="fk_dataset_worker_credentials_worker", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by_credential_id"], ["dataset_worker_credentials.credential_id"],
            name="fk_dataset_worker_credentials_replaced_by", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("credential_id", name="uq_dataset_worker_credential_public_id"),
        sa.CheckConstraint("length(secret_sha256) = 64", name="ck_dataset_worker_credential_digest"),
        sa.CheckConstraint("expires_at > created_at", name="ck_dataset_worker_credential_expiry"),
    )
    op.create_index(
        "ix_dataset_worker_credentials_worker_id", "dataset_worker_credentials", ["worker_id"]
    )
    op.create_index(
        "ix_dataset_worker_credentials_worker_expiry",
        "dataset_worker_credentials", ["worker_id", "expires_at"],
    )

    op.create_table(
        "dataset_worker_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("worker_id", sa.String(length=160), nullable=False),
        sa.Column("credential_id", sa.String(length=32), nullable=True),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["worker_id"], ["dataset_workers.worker_id"],
            name="fk_dataset_worker_events_worker", ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_type IN ('WORKER_REGISTERED', 'CREDENTIAL_ISSUED', 'CREDENTIAL_ROTATED', "
            "'CREDENTIAL_REVOKED', 'WORKER_DISABLED')",
            name="ck_dataset_worker_event_type",
        ),
    )
    op.create_index("ix_dataset_worker_events_worker_id", "dataset_worker_events", ["worker_id"])
    op.create_index(
        "ix_dataset_worker_events_worker_created",
        "dataset_worker_events", ["worker_id", "created_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION prevent_dataset_worker_event_mutation_0060()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'dataset worker security events are append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_worker_events_append_only_0060
            BEFORE UPDATE OR DELETE ON dataset_worker_events
            FOR EACH ROW EXECUTE FUNCTION prevent_dataset_worker_event_mutation_0060()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_dataset_worker_events_no_update_0060
            BEFORE UPDATE ON dataset_worker_events
            BEGIN
                SELECT RAISE(ABORT, 'dataset worker security events are append-only');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_dataset_worker_events_no_delete_0060
            BEFORE DELETE ON dataset_worker_events
            BEGIN
                SELECT RAISE(ABORT, 'dataset worker security events are append-only');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_worker_events_append_only_0060 ON dataset_worker_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_dataset_worker_event_mutation_0060()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_worker_events_no_update_0060")
        op.execute("DROP TRIGGER IF EXISTS trg_dataset_worker_events_no_delete_0060")
    op.drop_index("ix_dataset_worker_events_worker_created", table_name="dataset_worker_events")
    op.drop_index("ix_dataset_worker_events_worker_id", table_name="dataset_worker_events")
    op.drop_table("dataset_worker_events")
    op.drop_index("ix_dataset_worker_credentials_worker_expiry", table_name="dataset_worker_credentials")
    op.drop_index("ix_dataset_worker_credentials_worker_id", table_name="dataset_worker_credentials")
    op.drop_table("dataset_worker_credentials")
    op.drop_index("ix_dataset_workers_status_created", table_name="dataset_workers")
    op.drop_table("dataset_workers")
