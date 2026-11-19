"""Persist short-lived worker request nonces to reject replayed signatures."""

from alembic import op
import sqlalchemy as sa

revision = "0061_dataset_worker_request_nonces"
down_revision = "0060_dataset_worker_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dataset_worker_request_nonces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("credential_id", sa.String(length=32), nullable=False),
        sa.Column("nonce_sha256", sa.String(length=64), nullable=False),
        sa.Column("request_timestamp", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["credential_id"], ["dataset_worker_credentials.credential_id"],
            name="fk_dataset_worker_request_nonces_credential", ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "credential_id", "nonce_sha256",
            name="uq_dataset_worker_request_nonce_credential_digest",
        ),
        sa.CheckConstraint("length(nonce_sha256) = 64", name="ck_dataset_worker_request_nonce_digest"),
    )
    op.create_index(
        "ix_dataset_worker_request_nonces_expires",
        "dataset_worker_request_nonces", ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_dataset_worker_request_nonces_expires", table_name="dataset_worker_request_nonces")
    op.drop_table("dataset_worker_request_nonces")
