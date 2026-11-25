"""Audit changes to store-specific WMS backroom authority."""
from alembic import op
import sqlalchemy as sa

revision = "0085_inventory_backroom_policy_audit"
down_revision = "0084_wms_backroom_location_authority"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "inventory_freshness_policy_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "policy_id",
            sa.Integer(),
            sa.ForeignKey("inventory_freshness_policies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("previous_backroom_location_code", sa.String(length=120), nullable=True),
        sa.Column("new_backroom_location_code", sa.String(length=120), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "previous_backroom_location_code IS NULL OR length(trim(previous_backroom_location_code)) > 0",
            name="ck_inventory_freshness_event_previous_location",
        ),
        sa.CheckConstraint(
            "new_backroom_location_code IS NULL OR length(trim(new_backroom_location_code)) > 0",
            name="ck_inventory_freshness_event_new_location",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) >= 5",
            name="ck_inventory_freshness_event_reason_nonblank",
        ),
    )
    op.create_index(
        "ix_inventory_freshness_policy_events_policy",
        "inventory_freshness_policy_events",
        ["policy_id", "created_at", "id"],
    )
    op.create_index(
        "ix_inventory_freshness_policy_events_actor",
        "inventory_freshness_policy_events",
        ["actor_user_id", "created_at"],
    )
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION guard_inventory_freshness_policy_events_0085() "
            "RETURNS trigger AS $$ BEGIN RAISE EXCEPTION "
            "'inventory freshness policy events are append-only'; END; $$ LANGUAGE plpgsql"
        )
        op.execute(
            "CREATE TRIGGER trg_inventory_freshness_policy_events_0085 "
            "BEFORE UPDATE OR DELETE ON inventory_freshness_policy_events "
            "FOR EACH ROW EXECUTE FUNCTION guard_inventory_freshness_policy_events_0085()"
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_inventory_freshness_policy_events_update_0085 "
            "BEFORE UPDATE ON inventory_freshness_policy_events BEGIN "
            "SELECT RAISE(ABORT, 'inventory freshness policy events are append-only'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_inventory_freshness_policy_events_delete_0085 "
            "BEFORE DELETE ON inventory_freshness_policy_events BEGIN "
            "SELECT RAISE(ABORT, 'inventory freshness policy events are append-only'); END"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_inventory_freshness_policy_events_0085 "
            "ON inventory_freshness_policy_events"
        )
        op.execute("DROP FUNCTION IF EXISTS guard_inventory_freshness_policy_events_0085()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_freshness_policy_events_update_0085")
        op.execute("DROP TRIGGER IF EXISTS trg_inventory_freshness_policy_events_delete_0085")
    op.drop_index("ix_inventory_freshness_policy_events_actor", table_name="inventory_freshness_policy_events")
    op.drop_index("ix_inventory_freshness_policy_events_policy", table_name="inventory_freshness_policy_events")
    op.drop_table("inventory_freshness_policy_events")
