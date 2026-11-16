from types import SimpleNamespace

import pytest

from app.artifact_lineage import ArtifactLineageError, resolve_artifact_parent_chain


def reference(reference_id, parent_id=None, image_id=7, store_id=4):
    return SimpleNamespace(
        id=reference_id,
        parent_reference_id=parent_id,
        shelf_image_id=image_id,
        store_id=store_id,
    )


def test_resolves_parent_chain_from_artifact_to_root():
    root = reference(10)
    parent = reference(11, 10)
    child = reference(12, 11)

    chain = resolve_artifact_parent_chain(
        artifact_id=12,
        references={10: root, 11: parent, 12: child},
        expected_image_id=7,
        expected_store_id=4,
    )

    assert [item.id for item in chain] == [12, 11, 10]


@pytest.mark.parametrize(
    ("references", "reason"),
    [
        ({12: reference(12, 99)}, "artifact_parent_missing"),
        ({12: reference(12, 12)}, "artifact_parent_cycle"),
        ({12: reference(12, 11), 11: reference(11, 12)}, "artifact_parent_cycle"),
        ({12: reference(12, 11), 11: reference(11, image_id=8)}, "artifact_parent_image_mismatch"),
        ({12: reference(12, 11), 11: reference(11, store_id=9)}, "artifact_parent_store_mismatch"),
    ],
)
def test_rejects_broken_parent_chains(references, reason):
    with pytest.raises(ArtifactLineageError, match=reason):
        resolve_artifact_parent_chain(
            artifact_id=12,
            references=references,
            expected_image_id=7,
            expected_store_id=4,
        )


def test_handles_long_parent_chains_without_recursion():
    references = {
        item_id: reference(item_id, item_id - 1 if item_id > 1 else None)
        for item_id in range(1, 1501)
    }

    chain = resolve_artifact_parent_chain(
        artifact_id=1500,
        references=references,
        expected_image_id=7,
        expected_store_id=4,
    )

    assert len(chain) == 1500
    assert chain[0].id == 1500
    assert chain[-1].id == 1


@pytest.mark.parametrize(
    ("artifact_id", "image_id", "store_id"),
    [(True, 7, 4), (12, True, 4), (12, 7, True)],
)
def test_rejects_boolean_scope_identifiers(artifact_id, image_id, store_id):
    with pytest.raises(ValueError, match="positive integers"):
        resolve_artifact_parent_chain(
            artifact_id=artifact_id,
            references={12: reference(12)},
            expected_image_id=image_id,
            expected_store_id=store_id,
        )


def test_rejects_boolean_parent_identifier():
    with pytest.raises(ArtifactLineageError, match="artifact_parent_reference_invalid"):
        resolve_artifact_parent_chain(
            artifact_id=12,
            references={12: reference(12, True)},
            expected_image_id=7,
            expected_store_id=4,
        )
