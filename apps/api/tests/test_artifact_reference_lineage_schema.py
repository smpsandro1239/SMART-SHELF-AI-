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
