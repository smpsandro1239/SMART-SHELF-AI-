"""Database tests for immutable shelf ownership of embedding source images."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0100_embedding_source_image_shelf_lineage.py"
    )
    spec = importlib.util.spec_from_file_location(
        "embedding_source_image_shelf_lineage", path
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)
    return migration


def test_source_image_shelf_cannot_change_while_embedding_exemplar_exists(tmp_path):
    migration = _load_migration()
    engine = create_engine(f"sqlite:///{tmp_path / 'embedding-image-lineage.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE shelf_images (id INTEGER PRIMARY KEY, shelf_id INTEGER NOT NULL)"
        )
        connection.exec_driver_sql(
            "CREATE TABLE product_embedding_exemplars ("
            "id INTEGER PRIMARY KEY, shelf_image_id INTEGER NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO shelf_images VALUES (1, 10), (2, 20)"
        )
        connection.exec_driver_sql(
            "INSERT INTO product_embedding_exemplars VALUES (1, 1)"
        )

        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        with pytest.raises(
            IntegrityError,
            match="shelf image shelf cannot change while embedding exemplars reference it",
        ):
            connection.exec_driver_sql(
                "UPDATE shelf_images SET shelf_id = 30 WHERE id = 1"
            )

        connection.exec_driver_sql(
            "UPDATE shelf_images SET shelf_id = 30 WHERE id = 2"
        )
        assert connection.exec_driver_sql(
            "SELECT shelf_id FROM shelf_images WHERE id = 2"
        ).scalar_one() == 30

        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()

        connection.exec_driver_sql(
            "UPDATE shelf_images SET shelf_id = 40 WHERE id = 1"
        )
        assert connection.exec_driver_sql(
            "SELECT shelf_id FROM shelf_images WHERE id = 1"
        ).scalar_one() == 40
    engine.dispose()
