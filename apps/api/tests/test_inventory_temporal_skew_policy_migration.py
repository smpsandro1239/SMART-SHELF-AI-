"""SQLite migration contract for audited ERP/WMS temporal skew policy."""
import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_temporal_skew_policy_migration_enforces_erp_scope_and_audit_shape(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0093_inventory_temporal_skew_policy.py"
    spec = importlib.util.spec_from_file_location("inventory_temporal_skew_policy_migration", path)
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'temporal-skew-policy.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE inventory_freshness_policies (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL, source VARCHAR(20) NOT NULL, max_age_minutes INTEGER NOT NULL, backroom_location_code VARCHAR(120))")
        connection.exec_driver_sql("CREATE TABLE inventory_freshness_policy_events (id INTEGER PRIMARY KEY, policy_id INTEGER NOT NULL, actor_user_id INTEGER NOT NULL, previous_backroom_location_code VARCHAR(120), new_backroom_location_code VARCHAR(120), reason TEXT NOT NULL, created_at DATETIME NOT NULL)")
        connection.exec_driver_sql("INSERT INTO inventory_freshness_policies (id, store_id, source, max_age_minutes) VALUES (1, 10, 'ERP', 240), (2, 10, 'WMS', 240)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.exec_driver_sql("UPDATE inventory_freshness_policies SET comparison_skew_tolerance_minutes = 0 WHERE id = 1")
        connection.exec_driver_sql("UPDATE inventory_freshness_policies SET comparison_skew_tolerance_minutes = 10080 WHERE id = 1")
        for policy_id, value in ((1, -1), (1, 10081), (2, 5)):
            with pytest.raises(IntegrityError, match="invalid ERP/WMS comparison skew policy"):
                connection.exec_driver_sql("UPDATE inventory_freshness_policies SET comparison_skew_tolerance_minutes = ? WHERE id = ?", (value, policy_id))
        connection.exec_driver_sql("""INSERT INTO inventory_freshness_policy_events (id, policy_id, actor_user_id, previous_comparison_skew_tolerance_minutes, new_comparison_skew_tolerance_minutes, reason, created_at) VALUES (1, 1, 30, NULL, 0, 'Initial ERP/WMS skew policy', CURRENT_TIMESTAMP)""")
        with pytest.raises(IntegrityError, match="invalid inventory freshness policy audit event"):
            connection.exec_driver_sql("INSERT INTO inventory_freshness_policy_events (id, policy_id, actor_user_id, reason, created_at) VALUES (2, 1, 30, 'No changed values', CURRENT_TIMESTAMP)")
        with pytest.raises(IntegrityError, match="invalid inventory freshness policy audit event"):
            connection.exec_driver_sql("INSERT INTO inventory_freshness_policy_events (id, policy_id, actor_user_id, new_comparison_skew_tolerance_minutes, reason, created_at) VALUES (3, 1, 30, 10081, 'Out of range', CURRENT_TIMESTAMP)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        policy_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(inventory_freshness_policies)").all()}
        event_columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(inventory_freshness_policy_events)").all()}
        assert "comparison_skew_tolerance_minutes" not in policy_columns
        assert "previous_comparison_skew_tolerance_minutes" not in event_columns
        assert "new_comparison_skew_tolerance_minutes" not in event_columns
    engine.dispose()
