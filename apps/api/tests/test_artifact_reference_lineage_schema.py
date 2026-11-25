"""Schema contract for persisted external-artifact parent lineage."""

import pytest
from pydantic import ValidationError

from app.models import ShelfImageArtifactReference
from app.schemas import ShelfImageArtifactReferenceCreate, ShelfImageArtifactReferenceRead


def test_artifact_reference_parent_lineage_is_scoped_to_same_image_and_store():
    table = ShelfImageArtifactReference.__table__
    parent_fk = next(
        constraint
        for constraint in table.foreign_key_constraints
        if constraint.name == "fk_artifact_reference_parent_lineage"
    )

    assert [column.name for column in parent_fk.columns] == [
        "parent_reference_id",
        "shelf_image_id",
        "store_id",
    ]
    assert [element.target_fullname for element in parent_fk.elements] == [
        "shelf_image_artifact_references.id",
        "shelf_image_artifact_references.shelf_image_id",
        "shelf_image_artifact_references.store_id",
    ]
    assert parent_fk.ondelete == "RESTRICT"


def test_artifact_reference_parent_lineage_allows_roots_but_rejects_self_parent():
    table = ShelfImageArtifactReference.__table__
    parent_check = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "ck_artifact_reference_parent_not_self"
    )

    assert "parent_reference_id IS NULL" in str(parent_check.sqltext)
    assert "parent_reference_id <> id" in str(parent_check.sqltext)
    assert table.c.parent_reference_id.nullable is True


def test_artifact_reference_api_accepts_an_optional_parent_reference():
    payload = ShelfImageArtifactReferenceCreate(
        artifact_type="CROP",
        external_system="object-store-a",
        external_reference="bucket/crops/child.jpg",
        parent_reference_id=41,
        sha256="a" * 64,
    )

    assert payload.parent_reference_id == 41


def test_artifact_reference_api_rejects_non_positive_parent_ids():
    with pytest.raises(ValidationError):
        ShelfImageArtifactReferenceCreate(
            artifact_type="CROP",
            external_system="object-store-a",
            external_reference="bucket/crops/child.jpg",
            parent_reference_id=0,
        )


def test_artifact_reference_read_schema_exposes_parent_lineage():
    payload = ShelfImageArtifactReferenceRead.model_fields

    assert "parent_reference_id" in payload
    assert payload["parent_reference_id"].annotation == int | None

def test_sqlite_migration_rejects_parent_lineage_mutation(tmp_path):
    import importlib.util
    from pathlib import Path
    
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine
    from sqlalchemy.exc import IntegrityError

    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "0046_artifact_parent_lineage_immutable.py"
    )
    spec = importlib.util.spec_from_file_location(
        "artifact_parent_lineage_immutable_migration", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine(f"sqlite:///{tmp_path / 'lineage.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE shelf_image_artifact_references (
                id INTEGER PRIMARY KEY,
                shelf_image_id INTEGER NOT NULL,
                store_id INTEGER NOT NULL,
                parent_reference_id INTEGER
            )
            """
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

        connection.exec_driver_sql(
            "INSERT INTO shelf_image_artifact_references "
            "(id, shelf_image_id, store_id, parent_reference_id) VALUES "
            "(1, 7, 4, NULL), (2, 7, 4, 1), (3, 7, 4, NULL)"
        )
        with pytest.raises(IntegrityError, match="artifact parent lineage is immutable"):
            connection.exec_driver_sql(
                "UPDATE shelf_image_artifact_references "
                "SET parent_reference_id = 3 WHERE id = 2"
            )

        # No-op updates remain valid and do not rewrite the lineage.
        connection.exec_driver_sql(
            "UPDATE shelf_image_artifact_references "
            "SET parent_reference_id = 1 WHERE id = 2"
        )

        # Downgrade removes the guard and restores the pre-migration behaviour.
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        connection.exec_driver_sql(
            "UPDATE shelf_image_artifact_references "
            "SET parent_reference_id = 3 WHERE id = 2"
        )
        parent_id = connection.exec_driver_sql(
            "SELECT parent_reference_id FROM shelf_image_artifact_references WHERE id = 2"
        ).scalar_one()
        assert parent_id == 3
    engine.dispose()



def test_artifact_reference_api_rejects_boolean_parent_ids():
    # bool is a subclass of int in Python; accepting True as ID 1 is unsafe.
    with pytest.raises(ValidationError):
        ShelfImageArtifactReferenceCreate(
            artifact_type="CROP",
            external_system="object-store-a",
            external_reference="bucket/crops/boolean-parent.jpg",
            parent_reference_id=True,
        )
