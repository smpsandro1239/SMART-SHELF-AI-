"""SQLite coverage for Edge device telemetry schema revision 0072."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load(name):
    path = Path(__file__).parents[1] / "migrations" / "versions" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(module, connection, operation):
    with Operations.context(MigrationContext.configure(connection)):
        getattr(module, operation)()


def test_edge_device_telemetry_schema_validates_health_values_and_downgrades(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'edge-telemetry.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE stores (id INTEGER PRIMARY KEY, code VARCHAR(50) NOT NULL)")
        db.exec_driver_sql("INSERT INTO stores (id, code) VALUES (1, 'store-a')")
        _apply(_load("0071_edge_device_registry.py"), db, "upgrade")
        migration = _load("0072_edge_device_telemetry.py")
        _apply(migration, db, "upgrade")
        now = "2026-11-23T10:00:00+00:00"
        db.exec_driver_sql(
            "INSERT INTO edge_devices (device_id, store_id, device_type, status, created_at, last_seen_at, last_network_status, firmware_version, battery_pct, storage_free_bytes) VALUES ('camera-a', 1, 'fixed_camera', 'ACTIVE', ?, ?, 'ONLINE', '1.0.0', 87.5, 4096)",
            (now, now),
        )
        assert db.exec_driver_sql("SELECT last_network_status FROM edge_devices WHERE device_id='camera-a'").scalar_one() == "ONLINE"
        with pytest.raises(IntegrityError, match="telemetry violates health constraints"):
            db.exec_driver_sql("UPDATE edge_devices SET battery_pct=101 WHERE device_id='camera-a'")
        with pytest.raises(IntegrityError, match="CHECK constraint"):
            db.exec_driver_sql("UPDATE edge_devices SET last_network_status='UNKNOWN' WHERE device_id='camera-a'")
        _apply(migration, db, "downgrade")
        columns = {row[1] for row in db.exec_driver_sql("PRAGMA table_info(edge_devices)")}
        assert "last_seen_at" not in columns
        assert "battery_pct" not in columns
    engine.dispose()
