"""Add append-only two-person external artifact disposition events."""
from alembic import op
import sqlalchemy as sa

revision = "0034_shelf_image_artifact_disposition_events"
down_revision = "0033_shelf_image_artifact_references"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_shelf_image_artifact_reference_lineage",
        "shelf_image_artifact_references",
        ["id", "shelf_image_id", "store_id"],
        unique=True,
    )
    op.create_table(
        "shelf_image_artifact_disposition_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "artifact_reference_id",
            sa.Integer(),
            sa.ForeignKey("shelf_image_artifact_references.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "shelf_image_id",
            sa.Integer(),
            sa.ForeignKey("shelf_images.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "store_id",
            sa.Integer(),
            sa.ForeignKey("stores.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence_reference", sa.String(length=500), nullable=True),
        sa.Column("evidence_sha256", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["artifact_reference_id", "shelf_image_id", "store_id"],
            [
                "shelf_image_artifact_references.id",
                "shelf_image_artifact_references.shelf_image_id",
                "shelf_image_artifact_references.store_id",
            ],
            name="fk_shelf_image_artifact_disposition_reference_lineage",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "event_type IN ('PROPOSED', 'APPROVED', 'REJECTED', 'DISPOSAL_ATTESTED')",
            name="ck_shelf_image_artifact_disposition_event_type",
        ),
        sa.CheckConstraint(
            "evidence_sha256 IS NULL OR length(evidence_sha256) = 64",
            name="ck_shelf_image_artifact_disposition_evidence_sha256_length",
        ),
    )
    op.create_index(
        "ix_shelf_image_artifact_disposition_events_shelf_image_id",
        "shelf_image_artifact_disposition_events",
        ["shelf_image_id"],
    )
    op.create_index(
        "ix_shelf_image_artifact_disposition_events_store_id",
        "shelf_image_artifact_disposition_events",
        ["store_id"],
    )
    op.create_index(
        "ix_shelf_image_artifact_disposition_artifact_created",
        "shelf_image_artifact_disposition_events",
        ["artifact_reference_id", "created_at"],
    )
    op.create_index(
        "ix_shelf_image_artifact_disposition_store_image",
        "shelf_image_artifact_disposition_events",
        ["store_id", "shelf_image_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_shelf_image_artifact_disposition_event_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'shelf_image_artifact_disposition_events is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_append_only
            BEFORE UPDATE OR DELETE ON shelf_image_artifact_disposition_events
            FOR EACH ROW EXECUTE FUNCTION prevent_shelf_image_artifact_disposition_event_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_no_update
            BEFORE UPDATE ON shelf_image_artifact_disposition_events
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_disposition_events is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_disposition_events_no_delete
            BEFORE DELETE ON shelf_image_artifact_disposition_events
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_disposition_events is append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_append_only ON shelf_image_artifact_disposition_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_image_artifact_disposition_event_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_disposition_events_no_delete")

    op.drop_index(
        "ix_shelf_image_artifact_disposition_store_image",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_artifact_created",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_events_store_id",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_index(
        "ix_shelf_image_artifact_disposition_events_shelf_image_id",
        table_name="shelf_image_artifact_disposition_events",
    )
    op.drop_table("shelf_image_artifact_disposition_events")
    op.drop_index(
        "uq_shelf_image_artifact_reference_lineage",
        table_name="shelf_image_artifact_references",
    )
