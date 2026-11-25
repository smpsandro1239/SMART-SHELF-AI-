"""SQLite migration guards for persistent ONNX model release trust state (0069)."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _apply_migration(connection):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0069_vision_model_release_trust_state.py"
    )
    spec = importlib.util.spec_from_file_location("vision_model_release_0069", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    return migration


def test_vision_model_release_state_is_monotonic_and_events_are_append_only(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'vision-model-release.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        migration = _apply_migration(db)
        db.exec_driver_sql(
            """
            INSERT INTO vision_model_release_states
            (deployment_id, model_id, highest_release_version, manifest_sha256,
             key_id, detector_sha256, embedding_sha256, updated_at)
            VALUES ('edge-a', 'shelf-detector', 2, ?, 'release-a', ?, NULL, ?)
            """,
            ("a" * 64, "b" * 64, "2026-11-22T10:00:00+00:00"),
        )
        db.exec_driver_sql(
            """
            INSERT INTO vision_model_release_events
            (deployment_id, model_id, release_version, manifest_sha256, key_id,
             decision, reason, created_at)
            VALUES ('edge-a', 'shelf-detector', 2, ?, 'release-a',
                    'ACCEPTED', 'initial release', ?)
            """,
            ("a" * 64, "2026-11-22T10:00:00+00:00"),
        )
        with pytest.raises(IntegrityError, match="monotonically"):
            db.exec_driver_sql(
                "UPDATE vision_model_release_states SET highest_release_version=1 WHERE deployment_id='edge-a'"
            )
        with pytest.raises(IntegrityError, match="model identity"):
            db.exec_driver_sql(
                "UPDATE vision_model_release_states SET model_id='other', highest_release_version=3 WHERE deployment_id='edge-a'"
            )
        with pytest.raises(IntegrityError, match="cannot be deleted"):
            db.exec_driver_sql("DELETE FROM vision_model_release_states WHERE deployment_id='edge-a'")
        with pytest.raises(IntegrityError, match="append-only"):
            db.exec_driver_sql("UPDATE vision_model_release_events SET reason='tampered' WHERE id=1")
        with pytest.raises(IntegrityError, match="append-only"):
            db.exec_driver_sql("DELETE FROM vision_model_release_events WHERE id=1")
        with pytest.raises(RuntimeError, match="Refusing to downgrade"):
            with Operations.context(MigrationContext.configure(db)):
                migration.downgrade()
        assert db.exec_driver_sql(
            "SELECT highest_release_version FROM vision_model_release_states WHERE deployment_id='edge-a'"
        ).scalar_one() == 2
        assert db.exec_driver_sql(
            "SELECT COUNT(*) FROM vision_model_release_events"
        ).scalar_one() == 1
    engine.dispose()


def test_vision_model_release_state_allows_only_strictly_higher_version_updates(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'vision-model-release-upgrade.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        _apply_migration(db)
        db.exec_driver_sql(
            """
            INSERT INTO vision_model_release_states
            (deployment_id, model_id, highest_release_version, manifest_sha256,
             key_id, detector_sha256, embedding_sha256, updated_at)
            VALUES ('edge-b', 'shelf-detector', 2, ?, 'release-a', ?, NULL, ?)
            """,
            ("a" * 64, "b" * 64, "2026-11-22T10:00:00+00:00"),
        )
        db.exec_driver_sql(
            """
            UPDATE vision_model_release_states
            SET highest_release_version=3, manifest_sha256=?, key_id='release-b', updated_at=?
            WHERE deployment_id='edge-b'
            """,
            ("c" * 64, "2026-11-22T11:00:00+00:00"),
        )
        assert db.exec_driver_sql(
            "SELECT highest_release_version FROM vision_model_release_states WHERE deployment_id='edge-b'"
        ).scalar_one() == 3
    engine.dispose()



def test_runtime_trust_acl_migration_is_postgresql_only(tmp_path, monkeypatch):
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0070_vision_model_trust_runtime_readonly.py"
    )
    spec = importlib.util.spec_from_file_location("vision_model_trust_runtime_readonly_0070", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    monkeypatch.setenv("APP_DB_USER", "smart_shelf_runtime")
    engine = create_engine(f"sqlite:///{tmp_path / 'vision-model-trust-acl.db'}")
    with engine.begin() as db:
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
            migration.downgrade()
    engine.dispose()
