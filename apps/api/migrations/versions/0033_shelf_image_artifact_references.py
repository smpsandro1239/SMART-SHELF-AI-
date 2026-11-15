"""Register declared external artifacts derived from shelf images.

Declarations are append-only inventory records, not proof of deletion or disposition.
"""
from alembic import op
import sqlalchemy as sa

revision = "0033_shelf_image_artifact_references"
down_revision = "0032_shelf_image_purge_schedule_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelf_image_artifact_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("shelf_image_id", sa.Integer(), sa.ForeignKey("shelf_images.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("artifact_type", sa.String(length=24), nullable=False),
        sa.Column("external_system", sa.String(length=120), nullable=False),
        sa.Column("external_reference", sa.String(length=500), nullable=False),
        sa.Column("release_id", sa.String(length=160), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("declared_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "artifact_type IN ('DATASET_COPY', 'DATASET_RELEASE', 'CROP', 'REPORT', 'BACKUP', 'CACHE', 'OBJECT_REPLICA', 'OTHER')",
            name="ck_shelf_image_artifact_type",
        ),
        sa.CheckConstraint("sha256 IS NULL OR length(sha256) = 64", name="ck_shelf_image_artifact_sha256_length"),
        sa.UniqueConstraint(
            "shelf_image_id", "artifact_type", "external_system", "external_reference",
            name="uq_shelf_image_artifact_reference",
        ),
    )
    op.create_index("ix_shelf_image_artifact_references_shelf_image_id", "shelf_image_artifact_references", ["shelf_image_id"])
    op.create_index("ix_shelf_image_artifact_references_store_id", "shelf_image_artifact_references", ["store_id"])
    op.create_index("ix_shelf_image_artifacts_store_image", "shelf_image_artifact_references", ["store_id", "shelf_image_id"])
    op.create_index("ix_shelf_image_artifact_references_release_id", "shelf_image_artifact_references", ["release_id"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_shelf_image_artifact_reference_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'shelf_image_artifact_references is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_references_append_only
            BEFORE UPDATE OR DELETE ON shelf_image_artifact_references
            FOR EACH ROW EXECUTE FUNCTION prevent_shelf_image_artifact_reference_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_references_no_update
            BEFORE UPDATE ON shelf_image_artifact_references
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_references is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_references_no_delete
            BEFORE DELETE ON shelf_image_artifact_references
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_references is append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_references_append_only ON shelf_image_artifact_references")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_image_artifact_reference_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_references_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_references_no_delete")
    op.drop_index("ix_shelf_image_artifact_references_release_id", table_name="shelf_image_artifact_references")
    op.drop_index("ix_shelf_image_artifacts_store_image", table_name="shelf_image_artifact_references")
    op.drop_index("ix_shelf_image_artifact_references_store_id", table_name="shelf_image_artifact_references")
    op.drop_index("ix_shelf_image_artifact_references_shelf_image_id", table_name="shelf_image_artifact_references")
    op.drop_table("shelf_image_artifact_references")
