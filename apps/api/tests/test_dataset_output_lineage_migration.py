"""SQLite contract tests for append-only dataset-output lineage migration 0066."""
import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def test_dataset_output_lineage_rejects_cycles_and_mutation(tmp_path):
    path = Path(__file__).parents[1] / "migrations" / "versions" / "0066_dataset_output_lineage.py"
    spec = importlib.util.spec_from_file_location("dataset_output_lineage_0066", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'output-lineage.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, is_active BOOLEAN NOT NULL)")
        db.exec_driver_sql("CREATE TABLE dataset_execution_job_output_publications (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(db)):
            migration.upgrade()
        db.exec_driver_sql("INSERT INTO users VALUES (1,1)")
        db.exec_driver_sql("INSERT INTO users VALUES (2,0)")
        for publication_id in (10, 11, 12):
            db.exec_driver_sql("INSERT INTO dataset_execution_job_output_publications VALUES (?)", (publication_id,))
        insert = """
            INSERT INTO dataset_execution_job_output_lineage
            (parent_publication_id,child_publication_id,actor_user_id,reason,created_at)
            VALUES (?,?,?,?,?)
        """
        now = "2026-11-19T00:00:00+00:00"
        db.exec_driver_sql(insert, (10, 11, 1, "derived from parent", now))
        db.exec_driver_sql(insert, (11, 12, 1, "second generation", now))
        with pytest.raises(IntegrityError, match="cycle"):
            db.exec_driver_sql(insert, (12, 10, 1, "must not close a cycle", now))
        with pytest.raises(IntegrityError, match="active actor"):
            db.exec_driver_sql(insert, (10, 12, 2, "inactive actor", now))
        with pytest.raises(IntegrityError, match="append-only"):
            db.exec_driver_sql("UPDATE dataset_execution_job_output_lineage SET reason='tampered' WHERE parent_publication_id=10")
        with pytest.raises(IntegrityError, match="append-only"):
            db.exec_driver_sql("DELETE FROM dataset_execution_job_output_lineage WHERE parent_publication_id=10")
        assert db.exec_driver_sql("SELECT COUNT(*) FROM dataset_execution_job_output_lineage").scalar_one() == 2
        with Operations.context(MigrationContext.configure(db)):
            migration.downgrade()
    engine.dispose()
