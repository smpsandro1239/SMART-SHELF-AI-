"""Add immutable signed external artifact inventory snapshots."""
from alembic import op
import sqlalchemy as sa

revision = "0035_shelf_image_artifact_inventory_snapshots"
down_revision = "0034_shelf_image_artifact_disposition_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shelf_image_artifact_inventory_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
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
        sa.Column("external_system", sa.String(length=120), nullable=False),
        sa.Column("snapshot_id", sa.String(length=160), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("inventory_complete", sa.Boolean(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_signature", sa.String(length=64), nullable=False),
        sa.Column("inventory_manifest", sa.JSON(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("present_count", sa.Integer(), nullable=False),
        sa.Column("absent_count", sa.Integer(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "store_id", "external_system", "snapshot_id",
            name="uq_shelf_image_artifact_inventory_snapshot_source_id",
        ),
        sa.CheckConstraint("artifact_count >= 0", name="ck_artifact_inventory_count_nonnegative"),
        sa.CheckConstraint(
            "present_count >= 0 AND absent_count >= 0",
            name="ck_artifact_inventory_state_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "present_count + absent_count = artifact_count",
            name="ck_artifact_inventory_state_counts_total",
        ),
        sa.CheckConstraint(
            "length(manifest_sha256) = 64",
            name="ck_artifact_inventory_manifest_sha256_length",
        ),
        sa.CheckConstraint(
            "length(source_signature) = 64",
            name="ck_artifact_inventory_signature_length",
        ),
    )
    op.create_index(
        "ix_shelf_image_artifact_inventory_snapshots_shelf_image_id",
        "shelf_image_artifact_inventory_snapshots",
        ["shelf_image_id"],
    )
    op.create_index(
        "ix_shelf_image_artifact_inventory_snapshots_store_id",
        "shelf_image_artifact_inventory_snapshots",
        ["store_id"],
    )
    op.create_index(
        "ix_artifact_inventory_snapshot_image_source_time",
        "shelf_image_artifact_inventory_snapshots",
        ["shelf_image_id", "external_system", "generated_at"],
    )
    op.create_index(
        "ix_artifact_inventory_snapshot_store_source_time",
        "shelf_image_artifact_inventory_snapshots",
        ["store_id", "external_system", "generated_at"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION validate_shelf_image_artifact_inventory_snapshot()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            DECLARE
                actor_is_admin BOOLEAN;
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM shelf_images si
                    JOIN shelves sh ON sh.id = si.shelf_id
                    JOIN zones z ON z.id = sh.zone_id
                    WHERE si.id = NEW.shelf_image_id
                      AND z.store_id = NEW.store_id
                ) THEN
                    RAISE EXCEPTION 'inventory snapshot store does not match shelf image lineage'
                        USING ERRCODE = '23514';
                END IF;

                SELECT role = 'ADMIN' AND is_active IS TRUE
                INTO actor_is_admin
                FROM users
                WHERE id = NEW.created_by_user_id;

                IF COALESCE(actor_is_admin, FALSE) IS FALSE THEN
                    RAISE EXCEPTION 'inventory snapshot creator must be an active administrator'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_inventory_snapshot_validate
            BEFORE INSERT ON shelf_image_artifact_inventory_snapshots
            FOR EACH ROW EXECUTE FUNCTION validate_shelf_image_artifact_inventory_snapshot()
        """)
        op.execute("""
            CREATE FUNCTION prevent_shelf_image_artifact_inventory_snapshot_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'shelf_image_artifact_inventory_snapshots is append-only'
                    USING ERRCODE = '23514';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_inventory_snapshots_append_only
            BEFORE UPDATE OR DELETE ON shelf_image_artifact_inventory_snapshots
            FOR EACH ROW EXECUTE FUNCTION prevent_shelf_image_artifact_inventory_snapshot_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_inventory_snapshot_validate
            BEFORE INSERT ON shelf_image_artifact_inventory_snapshots
            BEGIN
                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1
                    FROM shelf_images si
                    JOIN shelves sh ON sh.id = si.shelf_id
                    JOIN zones z ON z.id = sh.zone_id
                    WHERE si.id = NEW.shelf_image_id
                      AND z.store_id = NEW.store_id
                ) THEN RAISE(ABORT, 'inventory snapshot store does not match shelf image lineage') END;

                SELECT CASE WHEN NOT EXISTS (
                    SELECT 1 FROM users
                    WHERE id = NEW.created_by_user_id AND role = 'ADMIN' AND is_active = 1
                ) THEN RAISE(ABORT, 'inventory snapshot creator must be an active administrator') END;
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_inventory_snapshots_no_update
            BEFORE UPDATE ON shelf_image_artifact_inventory_snapshots
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_inventory_snapshots is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_shelf_image_artifact_inventory_snapshots_no_delete
            BEFORE DELETE ON shelf_image_artifact_inventory_snapshots
            BEGIN SELECT RAISE(ABORT, 'shelf_image_artifact_inventory_snapshots is append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_inventory_snapshot_validate ON shelf_image_artifact_inventory_snapshots")
        op.execute("DROP FUNCTION IF EXISTS validate_shelf_image_artifact_inventory_snapshot()")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_inventory_snapshots_append_only ON shelf_image_artifact_inventory_snapshots")
        op.execute("DROP FUNCTION IF EXISTS prevent_shelf_image_artifact_inventory_snapshot_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_inventory_snapshot_validate")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_inventory_snapshots_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_shelf_image_artifact_inventory_snapshots_no_delete")

    op.drop_index(
        "ix_artifact_inventory_snapshot_store_source_time",
        table_name="shelf_image_artifact_inventory_snapshots",
    )
    op.drop_index(
        "ix_artifact_inventory_snapshot_image_source_time",
        table_name="shelf_image_artifact_inventory_snapshots",
    )
    op.drop_index(
        "ix_shelf_image_artifact_inventory_snapshots_store_id",
        table_name="shelf_image_artifact_inventory_snapshots",
    )
    op.drop_index(
        "ix_shelf_image_artifact_inventory_snapshots_shelf_image_id",
        table_name="shelf_image_artifact_inventory_snapshots",
    )
    op.drop_table("shelf_image_artifact_inventory_snapshots")
