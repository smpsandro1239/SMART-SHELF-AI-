"""SQLite migration contracts for versioned shelf planograms (0067–0068)."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _apply_migration(connection):
    migration_path = Path(__file__).parents[1] / "migrations" / "versions" / "0067_shelf_planograms.py"
    spec = importlib.util.spec_from_file_location("shelf_planograms_0067", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    return migration


def _apply_expected_facings_migration(connection):
    migration_path = Path(__file__).parents[1] / "migrations" / "versions" / "0068_shelf_planogram_expected_facings.py"
    spec = importlib.util.spec_from_file_location("shelf_planogram_expected_facings_0068", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()
    return migration


def _insert_planogram(connection, *, version, created_by=1, source="MANUAL", image_id=None, image_sha=None):
    connection.exec_driver_sql(
        """
        INSERT INTO shelf_planograms
        (shelf_id,version,status,calibration_source,calibration_image_id,
         calibration_image_sha256,created_by_user_id,created_at)
        VALUES (1,?,'DRAFT',?,?,?,?,?)
        """,
        (version, source, image_id, image_sha, created_by, "2026-11-19T10:00:00+00:00"),
    )
    return connection.exec_driver_sql("SELECT last_insert_rowid()").scalar_one()


def _insert_cell(connection, planogram_id, code, x_min, y_min, x_max, y_max, product_id=10, row=0, column=0, expected_facings=None):
    connection.exec_driver_sql(
        """
        INSERT INTO shelf_planogram_cells
        (planogram_id,cell_code,row_index,column_index,x_min,y_min,x_max,y_max,expected_product_id,expected_facings,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (planogram_id, code, row, column, x_min, y_min, x_max, y_max, product_id, expected_facings,
         "2026-11-19T10:00:00+00:00"),
    )


def _activate(connection, planogram_id, actor_id=1, reason="reviewed calibration"):
    connection.exec_driver_sql(
        """
        UPDATE shelf_planograms
        SET status='ACTIVE',activated_by_user_id=?,activated_at=?,activation_reason=?
        WHERE id=?
        """,
        (actor_id, "2026-11-19T11:00:00+00:00", reason, planogram_id),
    )


def _retire(connection, planogram_id, actor_id=1, reason="superseded calibration"):
    connection.exec_driver_sql(
        """
        UPDATE shelf_planograms
        SET status='RETIRED',retired_by_user_id=?,retired_at=?,retirement_reason=?
        WHERE id=?
        """,
        (actor_id, "2026-11-19T12:00:00+00:00", reason, planogram_id),
    )


def _engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'shelf-planograms.db'}")
    with engine.begin() as db:
        db.exec_driver_sql("PRAGMA foreign_keys=ON")
        db.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, is_active BOOLEAN NOT NULL)")
        db.exec_driver_sql("CREATE TABLE zones (id INTEGER PRIMARY KEY, store_id INTEGER NOT NULL)")
        db.exec_driver_sql("CREATE TABLE shelves (id INTEGER PRIMARY KEY, zone_id INTEGER NOT NULL REFERENCES zones(id))")
        db.exec_driver_sql("CREATE TABLE products (id INTEGER PRIMARY KEY, is_active BOOLEAN NOT NULL)")
        db.exec_driver_sql("CREATE TABLE shelf_products (shelf_id INTEGER NOT NULL, product_id INTEGER NOT NULL)")
        db.exec_driver_sql(
            "CREATE TABLE shelf_images (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL, "
            "sha256 VARCHAR(64) NOT NULL, retention_status VARCHAR(20) NOT NULL)"
        )
        _apply_migration(db)
        _apply_expected_facings_migration(db)
        db.exec_driver_sql("INSERT INTO users VALUES (1,1),(2,1),(3,0)")
        db.exec_driver_sql("INSERT INTO zones VALUES (1,100)")
        db.exec_driver_sql("INSERT INTO shelves VALUES (1,1)")
        db.exec_driver_sql("INSERT INTO products VALUES (10,1),(11,0),(12,1)")
        db.exec_driver_sql("INSERT INTO shelf_products VALUES (1,10),(1,12)")
        db.exec_driver_sql(
            "INSERT INTO shelf_images VALUES (20,1,?,'ACTIVE'),(21,1,?,'RESTRICTED'),(22,2,?,'ACTIVE')",
            ("a" * 64, "b" * 64, "c" * 64),
        )
    return engine


def test_planogram_versions_activation_retirement_and_cell_immutability(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as db:
        first = _insert_planogram(db, version=1)
        _insert_cell(db, first, "A1", 0.0, 0.0, 0.5, 1.0)
        _activate(db, first)
        with pytest.raises(IntegrityError, match="only DRAFT"):
            db.exec_driver_sql("UPDATE shelf_planogram_cells SET cell_code='tampered' WHERE planogram_id=?", (first,))
        with pytest.raises(IntegrityError, match="only DRAFT"):
            _insert_cell(db, first, "A2", 0.5, 0.0, 1.0, 1.0, row=0, column=1)

        second = _insert_planogram(db, version=2)
        _insert_cell(db, second, "B1", 0.0, 0.0, 1.0, 1.0, product_id=12)
        with pytest.raises(IntegrityError, match="UNIQUE"):
            _activate(db, second)

        _retire(db, first)
        _activate(db, second)
        with pytest.raises(IntegrityError, match="activated planogram history"):
            db.exec_driver_sql("DELETE FROM shelf_planograms WHERE id=?", (second,))
        with pytest.raises(IntegrityError, match="invalid planogram lifecycle"):
            db.exec_driver_sql("UPDATE shelf_planograms SET status='DRAFT' WHERE id=?", (second,))
        assert db.exec_driver_sql(
            "SELECT status FROM shelf_planograms WHERE id=?", (first,)
        ).scalar_one() == "RETIRED"
        assert db.exec_driver_sql(
            "SELECT status FROM shelf_planograms WHERE id=?", (second,)
        ).scalar_one() == "ACTIVE"
    engine.dispose()


def test_planogram_database_rejects_invalid_versions_cells_and_skus(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as db:
        with pytest.raises(IntegrityError, match="active creator"):
            _insert_planogram(db, version=1, created_by=3)
        first = _insert_planogram(db, version=1)
        with pytest.raises(IntegrityError, match="consecutive"):
            _insert_planogram(db, version=3)
        with pytest.raises(IntegrityError, match="active and assigned"):
            _insert_cell(db, first, "BAD-SKU", 0.0, 0.0, 0.5, 1.0, product_id=11)
        _insert_cell(db, first, "A1", 0.0, 0.0, 0.6, 1.0)
        with pytest.raises(IntegrityError, match="must not overlap"):
            _insert_cell(db, first, "A2", 0.5, 0.0, 1.0, 1.0, row=0, column=1)
        with pytest.raises(IntegrityError, match="UNIQUE"):
            _insert_cell(db, first, "A3", 0.7, 0.0, 1.0, 1.0, row=0, column=0)
        with pytest.raises(IntegrityError, match="bbox_normalized"):
            _insert_cell(db, first, "BAD-BOX", 0.8, 0.0, 0.7, 1.0, row=1, column=0)
        with pytest.raises(IntegrityError, match="cell_code_nonempty"):
            _insert_cell(db, first, " ", 0.7, 0.0, 0.8, 1.0, row=1, column=1)
    engine.dispose()


def test_image_calibration_requires_active_same_shelf_matching_digest(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as db:
        with pytest.raises(IntegrityError, match="not eligible"):
            _insert_planogram(db, version=1, source="IMAGE", image_id=21, image_sha="b" * 64)
        with pytest.raises(IntegrityError, match="not eligible"):
            _insert_planogram(db, version=1, source="IMAGE", image_id=20, image_sha="f" * 64)
        with pytest.raises(IntegrityError, match="not eligible"):
            _insert_planogram(db, version=1, source="IMAGE", image_id=22, image_sha="c" * 64)
        planogram_id = _insert_planogram(db, version=1, source="IMAGE", image_id=20, image_sha="a" * 64)
        _insert_cell(db, planogram_id, "A1", 0.0, 0.0, 1.0, 1.0)
        _activate(db, planogram_id)
        second = _insert_planogram(db, version=2, source="IMAGE", image_id=20, image_sha="a" * 64)
        _insert_cell(db, second, "B1", 0.0, 0.0, 1.0, 1.0)
        db.exec_driver_sql("UPDATE shelf_images SET retention_status='RESTRICTED' WHERE id=20")
        with pytest.raises(IntegrityError, match="not eligible"):
            _activate(db, second)
    engine.dispose()


def test_draft_delete_is_allowed_but_active_and_retired_history_is_preserved(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as db:
        draft = _insert_planogram(db, version=1)
        _insert_cell(db, draft, "A1", 0.0, 0.0, 1.0, 1.0)
        db.exec_driver_sql("DELETE FROM shelf_planograms WHERE id=?", (draft,))
        assert db.exec_driver_sql("SELECT COUNT(*) FROM shelf_planograms").scalar_one() == 0
        assert db.exec_driver_sql("SELECT COUNT(*) FROM shelf_planogram_cells").scalar_one() == 0
    engine.dispose()



def test_expected_facings_sqlite_guard_requires_positive_count_and_expected_sku(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as db:
        plan = _insert_planogram(db, version=1)
        with pytest.raises(IntegrityError, match="expected_facings"):
            _insert_cell(
                db, plan, "BAD-COUNT", 0.0, 0.0, 0.5, 1.0,
                expected_facings=0,
            )
        with pytest.raises(IntegrityError, match="expected_facings"):
            _insert_cell(
                db, plan, "NO-SKU", 0.5, 0.0, 1.0, 1.0,
                product_id=None, expected_facings=2, row=0, column=1,
            )
        _insert_cell(
            db, plan, "VALID", 0.0, 0.0, 0.5, 1.0,
            expected_facings=3,
        )
        assert db.exec_driver_sql(
            "SELECT expected_facings FROM shelf_planogram_cells WHERE cell_code='VALID'"
        ).scalar_one() == 3
    engine.dispose()
