"""Persist ONNX release high-water marks and append-only trust decisions."""
from alembic import op
import sqlalchemy as sa


revision = "0069_vision_model_release_trust_state"
down_revision = "0068_shelf_planogram_expected_facings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vision_model_release_states",
        sa.Column("deployment_id", sa.String(length=80), primary_key=True),
        sa.Column("model_id", sa.String(length=80), nullable=False),
        sa.Column("highest_release_version", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("detector_sha256", sa.String(length=64), nullable=False),
        sa.Column("embedding_sha256", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(trim(deployment_id)) BETWEEN 1 AND 80", name="ck_vision_release_state_deployment"),
        sa.CheckConstraint("length(trim(model_id)) BETWEEN 1 AND 80", name="ck_vision_release_state_model"),
        sa.CheckConstraint("highest_release_version > 0", name="ck_vision_release_state_version"),
        sa.CheckConstraint("length(manifest_sha256) = 64", name="ck_vision_release_state_manifest_digest"),
        sa.CheckConstraint("length(detector_sha256) = 64", name="ck_vision_release_state_detector_digest"),
        sa.CheckConstraint("embedding_sha256 IS NULL OR length(embedding_sha256) = 64", name="ck_vision_release_state_embedding_digest"),
    )
    op.create_table(
        "vision_model_release_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "deployment_id",
            sa.String(length=80),
            sa.ForeignKey("vision_model_release_states.deployment_id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("model_id", sa.String(length=80), nullable=False),
        sa.Column("release_version", sa.Integer(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('ACCEPTED', 'REJECTED_ROLLBACK', 'REJECTED_VERSION_COLLISION', 'REJECTED_MODEL_ID_CHANGE')",
            name="ck_vision_release_event_decision",
        ),
        sa.CheckConstraint("release_version > 0", name="ck_vision_release_event_version"),
        sa.CheckConstraint("length(manifest_sha256) = 64", name="ck_vision_release_event_manifest_digest"),
    )
    op.create_index(
        "ix_vision_model_release_events_deployment_created",
        "vision_model_release_events",
        ["deployment_id", "created_at", "id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION guard_vision_model_release_state_0069()
            RETURNS trigger AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'vision model release high-water marks cannot be deleted';
                END IF;
                IF NEW.deployment_id <> OLD.deployment_id
                   OR NEW.model_id <> OLD.model_id
                   OR NEW.highest_release_version <= OLD.highest_release_version THEN
                    RAISE EXCEPTION 'vision model release state must advance monotonically without changing model identity';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_vision_model_release_state_guard_0069
            BEFORE UPDATE OR DELETE ON vision_model_release_states
            FOR EACH ROW EXECUTE FUNCTION guard_vision_model_release_state_0069()
        """)
        op.execute("""
            CREATE OR REPLACE FUNCTION guard_vision_model_release_event_0069()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'vision model release events are append-only';
            END;
            $$ LANGUAGE plpgsql
        """)
        op.execute("""
            CREATE TRIGGER trg_vision_model_release_event_append_only_0069
            BEFORE UPDATE OR DELETE ON vision_model_release_events
            FOR EACH ROW EXECUTE FUNCTION guard_vision_model_release_event_0069()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_vision_model_release_state_update_0069
            BEFORE UPDATE ON vision_model_release_states
            WHEN NEW.deployment_id <> OLD.deployment_id
                 OR NEW.model_id <> OLD.model_id
                 OR NEW.highest_release_version <= OLD.highest_release_version
            BEGIN
                SELECT RAISE(ABORT, 'vision model release state must advance monotonically without changing model identity');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_vision_model_release_state_delete_0069
            BEFORE DELETE ON vision_model_release_states
            BEGIN
                SELECT RAISE(ABORT, 'vision model release high-water marks cannot be deleted');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_vision_model_release_event_update_0069
            BEFORE UPDATE ON vision_model_release_events
            BEGIN
                SELECT RAISE(ABORT, 'vision model release events are append-only');
            END
        """)
        op.execute("""
            CREATE TRIGGER trg_vision_model_release_event_delete_0069
            BEFORE DELETE ON vision_model_release_events
            BEGIN
                SELECT RAISE(ABORT, 'vision model release events are append-only');
            END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(sa.text("SELECT COUNT(*) FROM vision_model_release_states")).scalar_one()
    if count:
        raise RuntimeError(
            "Refusing to downgrade vision model anti-rollback state: accepted release high-water marks exist"
        )
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_vision_model_release_event_append_only_0069 ON vision_model_release_events")
        op.execute("DROP FUNCTION IF EXISTS guard_vision_model_release_event_0069()")
        op.execute("DROP TRIGGER IF EXISTS trg_vision_model_release_state_guard_0069 ON vision_model_release_states")
        op.execute("DROP FUNCTION IF EXISTS guard_vision_model_release_state_0069()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_vision_model_release_event_delete_0069")
        op.execute("DROP TRIGGER IF EXISTS trg_vision_model_release_event_update_0069")
        op.execute("DROP TRIGGER IF EXISTS trg_vision_model_release_state_delete_0069")
        op.execute("DROP TRIGGER IF EXISTS trg_vision_model_release_state_update_0069")
    op.drop_index("ix_vision_model_release_events_deployment_created", table_name="vision_model_release_events")
    op.drop_table("vision_model_release_events")
    op.drop_table("vision_model_release_states")
