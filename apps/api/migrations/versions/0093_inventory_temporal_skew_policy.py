"""Add an audited, optional ERP/WMS capture-time skew tolerance."""
from alembic import op
import sqlalchemy as sa

revision = "0093_inventory_temporal_skew_policy"
down_revision = "0092_inventory_snapshot_sync_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("inventory_freshness_policies", sa.Column("comparison_skew_tolerance_minutes", sa.Integer(), nullable=True))
    op.add_column("inventory_freshness_policy_events", sa.Column("previous_comparison_skew_tolerance_minutes", sa.Integer(), nullable=True))
    op.add_column("inventory_freshness_policy_events", sa.Column("new_comparison_skew_tolerance_minutes", sa.Integer(), nullable=True))
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_check_constraint("ck_inventory_freshness_comparison_skew_erp_only", "inventory_freshness_policies", "comparison_skew_tolerance_minutes IS NULL OR (source = 'ERP' AND comparison_skew_tolerance_minutes BETWEEN 0 AND 10080)")
        op.create_check_constraint("ck_inventory_freshness_event_previous_skew_range", "inventory_freshness_policy_events", "previous_comparison_skew_tolerance_minutes IS NULL OR previous_comparison_skew_tolerance_minutes BETWEEN 0 AND 10080")
        op.create_check_constraint("ck_inventory_freshness_event_new_skew_range", "inventory_freshness_policy_events", "new_comparison_skew_tolerance_minutes IS NULL OR new_comparison_skew_tolerance_minutes BETWEEN 0 AND 10080")
        op.create_check_constraint("ck_inventory_freshness_event_has_change", "inventory_freshness_policy_events", "previous_backroom_location_code IS NOT NULL OR new_backroom_location_code IS NOT NULL OR previous_comparison_skew_tolerance_minutes IS NOT NULL OR new_comparison_skew_tolerance_minutes IS NOT NULL")
    elif bind.dialect.name == "sqlite":
        op.execute("""CREATE TRIGGER trg_inventory_freshness_skew_policy_insert_0093 BEFORE INSERT ON inventory_freshness_policies WHEN NEW.comparison_skew_tolerance_minutes IS NOT NULL AND (NEW.source <> 'ERP' OR NEW.comparison_skew_tolerance_minutes < 0 OR NEW.comparison_skew_tolerance_minutes > 10080) BEGIN SELECT RAISE(ABORT, 'invalid ERP/WMS comparison skew policy'); END""")
        op.execute("""CREATE TRIGGER trg_inventory_freshness_skew_policy_update_0093 BEFORE UPDATE OF source, comparison_skew_tolerance_minutes ON inventory_freshness_policies WHEN NEW.comparison_skew_tolerance_minutes IS NOT NULL AND (NEW.source <> 'ERP' OR NEW.comparison_skew_tolerance_minutes < 0 OR NEW.comparison_skew_tolerance_minutes > 10080) BEGIN SELECT RAISE(ABORT, 'invalid ERP/WMS comparison skew policy'); END""")
        op.execute("""CREATE TRIGGER trg_inventory_freshness_skew_event_insert_0093 BEFORE INSERT ON inventory_freshness_policy_events WHEN (NEW.previous_comparison_skew_tolerance_minutes IS NOT NULL AND (NEW.previous_comparison_skew_tolerance_minutes < 0 OR NEW.previous_comparison_skew_tolerance_minutes > 10080)) OR (NEW.new_comparison_skew_tolerance_minutes IS NOT NULL AND (NEW.new_comparison_skew_tolerance_minutes < 0 OR NEW.new_comparison_skew_tolerance_minutes > 10080)) OR (NEW.previous_backroom_location_code IS NULL AND NEW.new_backroom_location_code IS NULL AND NEW.previous_comparison_skew_tolerance_minutes IS NULL AND NEW.new_comparison_skew_tolerance_minutes IS NULL) BEGIN SELECT RAISE(ABORT, 'invalid inventory freshness policy audit event'); END""")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name in ("ck_inventory_freshness_event_has_change", "ck_inventory_freshness_event_new_skew_range", "ck_inventory_freshness_event_previous_skew_range", "ck_inventory_freshness_comparison_skew_erp_only"):
            table = "inventory_freshness_policies" if name.endswith("erp_only") else "inventory_freshness_policy_events"
            op.drop_constraint(name, table, type_="check")
    elif bind.dialect.name == "sqlite":
        for name in ("trg_inventory_freshness_skew_event_insert_0093", "trg_inventory_freshness_skew_policy_update_0093", "trg_inventory_freshness_skew_policy_insert_0093"):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.drop_column("inventory_freshness_policy_events", "new_comparison_skew_tolerance_minutes")
    op.drop_column("inventory_freshness_policy_events", "previous_comparison_skew_tolerance_minutes")
    op.drop_column("inventory_freshness_policies", "comparison_skew_tolerance_minutes")
