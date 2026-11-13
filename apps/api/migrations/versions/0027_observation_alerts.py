"""Persist idempotent SKU observation alerts and immutable audit events."""
from alembic import op
import sqlalchemy as sa

revision = "0027_observation_alerts"
down_revision = "0026_observation_product_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "observation_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="CASCADE"), nullable=False),
        sa.Column("shelf_id", sa.Integer(), sa.ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("condition", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmation_count", sa.Integer(), nullable=False),
        sa.Column("average_confidence", sa.Float(), nullable=False),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.CheckConstraint("condition IN ('LOW_STOCK', 'EMPTY', 'MISPLACED', 'DAMAGED')", name="ck_observation_alert_condition"),
        sa.CheckConstraint("status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'DISMISSED')", name="ck_observation_alert_status"),
        sa.CheckConstraint("confirmation_count >= 2", name="ck_observation_alert_confirmations"),
        sa.CheckConstraint("average_confidence >= 0 AND average_confidence <= 1", name="ck_observation_alert_confidence"),
    )
    op.create_index("ix_observation_alerts_store_id", "observation_alerts", ["store_id"])
    op.create_index("ix_observation_alerts_shelf_id", "observation_alerts", ["shelf_id"])
    op.create_index("ix_observation_alerts_product_id", "observation_alerts", ["product_id"])
    op.create_index("ix_observation_alerts_status", "observation_alerts", ["status"])
    op.create_index("ix_observation_alert_store_status_created", "observation_alerts", ["store_id", "status", "created_at"])
    op.create_index(
        "uq_observation_alert_active_scope",
        "observation_alerts",
        ["store_id", "shelf_id", "product_id", "condition"],
        unique=True,
        postgresql_where=sa.text("status IN ('OPEN', 'ACKNOWLEDGED')"),
        sqlite_where=sa.text("status IN ('OPEN', 'ACKNOWLEDGED')"),
    )

    op.create_table(
        "observation_alert_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("alert_id", sa.Integer(), sa.ForeignKey("observation_alerts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=True),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_type IN ('CREATED', 'EVIDENCE_UPDATED', 'ACKNOWLEDGED', 'RESOLVED', 'DISMISSED')", name="ck_observation_alert_event_type"),
    )
    op.create_index("ix_observation_alert_events_alert_id", "observation_alert_events", ["alert_id"])
    op.create_index("ix_observation_alert_events_actor_user_id", "observation_alert_events", ["actor_user_id"])
    op.create_index("ix_observation_alert_events_created_at", "observation_alert_events", ["created_at"])
    op.create_index("ix_observation_alert_events_alert_created", "observation_alert_events", ["alert_id", "created_at"])

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE FUNCTION prevent_observation_alert_event_mutation()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'observation_alert_events is append-only';
            END;
            $function$
        """)
        op.execute("""
            CREATE TRIGGER trg_observation_alert_events_append_only
            BEFORE UPDATE OR DELETE ON observation_alert_events
            FOR EACH ROW EXECUTE FUNCTION prevent_observation_alert_event_mutation()
        """)
    elif bind.dialect.name == "sqlite":
        op.execute("""
            CREATE TRIGGER trg_observation_alert_events_no_update
            BEFORE UPDATE ON observation_alert_events
            BEGIN SELECT RAISE(ABORT, 'observation_alert_events is append-only'); END
        """)
        op.execute("""
            CREATE TRIGGER trg_observation_alert_events_no_delete
            BEFORE DELETE ON observation_alert_events
            BEGIN SELECT RAISE(ABORT, 'observation_alert_events is append-only'); END
        """)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_observation_alert_events_append_only ON observation_alert_events")
        op.execute("DROP FUNCTION IF EXISTS prevent_observation_alert_event_mutation()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_observation_alert_events_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_observation_alert_events_no_delete")
    op.drop_index("ix_observation_alert_events_alert_created", table_name="observation_alert_events")
    op.drop_index("ix_observation_alert_events_created_at", table_name="observation_alert_events")
    op.drop_index("ix_observation_alert_events_actor_user_id", table_name="observation_alert_events")
    op.drop_index("ix_observation_alert_events_alert_id", table_name="observation_alert_events")
    op.drop_table("observation_alert_events")
    op.drop_index("uq_observation_alert_active_scope", table_name="observation_alerts")
    op.drop_index("ix_observation_alert_store_status_created", table_name="observation_alerts")
    op.drop_index("ix_observation_alerts_status", table_name="observation_alerts")
    op.drop_index("ix_observation_alerts_product_id", table_name="observation_alerts")
    op.drop_index("ix_observation_alerts_shelf_id", table_name="observation_alerts")
    op.drop_index("ix_observation_alerts_store_id", table_name="observation_alerts")
    op.drop_table("observation_alerts")
