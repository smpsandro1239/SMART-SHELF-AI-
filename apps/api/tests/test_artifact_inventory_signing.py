from datetime import datetime, timedelta, timezone
import json

import pytest

from app.artifact_inventory_signing import (
    InventorySignatureConfigurationError,
    canonical_inventory_payload,
    inventory_signature,
    verify_inventory_signature,
)


SECRET = "test-inventory-secret-with-at-least-32-bytes"
GENERATED_AT = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
ENTRIES = [
    {
        "artifact_type": "BACKUP",
        "external_reference": "backup/object-2",
        "sha256": "b" * 64,
        "state": "ABSENT",
    },
    {
        "artifact_type": "CACHE",
        "external_reference": "cache/object-1",
        "sha256": None,
        "state": "PRESENT",
    },
]


def test_canonical_inventory_is_order_independent_and_timezone_normalized():
    first = canonical_inventory_payload(
        image_id=10,
        store_id=2,
        external_system="backup-vault",
        snapshot_id="snapshot-1",
        generated_at=GENERATED_AT,
        entries=ENTRIES,
        inventory_complete=True,
    )
    second = canonical_inventory_payload(
        image_id=10,
        store_id=2,
        external_system="backup-vault",
        snapshot_id="snapshot-1",
        generated_at=GENERATED_AT.astimezone(timezone(timedelta(hours=2))),
        entries=list(reversed(ENTRIES)),
        inventory_complete=True,
    )
    assert first == second


def test_inventory_signature_verifies_and_returns_manifest_digest():
    signature = inventory_signature(
        image_id=10,
        store_id=2,
        external_system="backup-vault",
        snapshot_id="snapshot-1",
        generated_at=GENERATED_AT,
        entries=ENTRIES,
        secret=SECRET,
        inventory_complete=True,
    )
    digest = verify_inventory_signature(
        image_id=10,
        store_id=2,
        external_system="backup-vault",
        snapshot_id="snapshot-1",
        generated_at=GENERATED_AT,
        entries=ENTRIES,
        signature=signature,
        configured_keys_json=json.dumps({"backup-vault": SECRET}),
        inventory_complete=True,
    )
    assert len(digest) == 64


def test_inventory_signature_rejects_tampered_manifest():
    signature = inventory_signature(
        image_id=10,
        store_id=2,
        external_system="backup-vault",
        snapshot_id="snapshot-1",
        generated_at=GENERATED_AT,
        entries=ENTRIES,
        secret=SECRET,
        inventory_complete=True,
    )
    altered = [dict(ENTRIES[0]), dict(ENTRIES[1])]
    altered[0]["state"] = "PRESENT"
    with pytest.raises(ValueError, match="signature is invalid"):
        verify_inventory_signature(
            image_id=10,
            store_id=2,
            external_system="backup-vault",
            snapshot_id="snapshot-1",
            generated_at=GENERATED_AT,
            entries=altered,
            signature=signature,
            configured_keys_json=json.dumps({"backup-vault": SECRET}),
            inventory_complete=True,
        )


def test_inventory_signature_rejects_unknown_source_and_weak_key():
    with pytest.raises(InventorySignatureConfigurationError):
        verify_inventory_signature(
            image_id=10,
            store_id=2,
            external_system="unconfigured-source",
            snapshot_id="snapshot-1",
            generated_at=GENERATED_AT,
            entries=ENTRIES,
            signature="a" * 64,
            configured_keys_json=json.dumps({"backup-vault": SECRET}),
            inventory_complete=True,
        )
    with pytest.raises(InventorySignatureConfigurationError):
        inventory_signature(
            image_id=10,
            store_id=2,
            external_system="backup-vault",
            snapshot_id="snapshot-1",
            generated_at=GENERATED_AT,
            entries=ENTRIES,
            secret="weak",
            inventory_complete=True,
        )


def test_canonical_inventory_rejects_non_complete_source_assertion():
    with pytest.raises(ValueError, match="complete inventory coverage"):
        canonical_inventory_payload(
            image_id=10,
            store_id=2,
            external_system="backup-vault",
            snapshot_id="snapshot-incomplete",
            generated_at=GENERATED_AT,
            entries=ENTRIES,
            inventory_complete=False,
        )


def test_canonical_inventory_rejects_duplicates_and_naive_timestamps():
    duplicate_entries = [dict(ENTRIES[0]), dict(ENTRIES[0])]
    with pytest.raises(ValueError, match="duplicate"):
        canonical_inventory_payload(
            image_id=10,
            store_id=2,
            external_system="backup-vault",
            snapshot_id="snapshot-1",
            generated_at=GENERATED_AT,
            entries=duplicate_entries,
            inventory_complete=True,
        )
    with pytest.raises(ValueError, match="timezone"):
        canonical_inventory_payload(
            image_id=10,
            store_id=2,
            external_system="backup-vault",
            snapshot_id="snapshot-1",
            generated_at=datetime(2026, 11, 16),
            entries=ENTRIES,
            inventory_complete=True,
        )



def test_inventory_key_configuration_rejects_duplicate_source_identifiers():
    duplicated = (
        '{"backup-vault":"' + SECRET + '","backup-vault":"'
        + ("x" * 40) + '"}'
    )
    with pytest.raises(InventorySignatureConfigurationError, match="duplicate source identifier"):
        verify_inventory_signature(
            image_id=10, store_id=2, external_system="backup-vault",
            snapshot_id="snapshot-duplicate-key", generated_at=GENERATED_AT,
            entries=ENTRIES, signature="a" * 64,
            configured_keys_json=duplicated, inventory_complete=True,
        )


@pytest.mark.parametrize("configuration", ["[]", '"not-an-object"', "{invalid-json"])
def test_inventory_key_configuration_must_be_a_json_object(configuration):
    with pytest.raises(InventorySignatureConfigurationError, match="JSON object"):
        verify_inventory_signature(
            image_id=10, store_id=2, external_system="backup-vault",
            snapshot_id="snapshot-invalid-config", generated_at=GENERATED_AT,
            entries=ENTRIES, signature="a" * 64,
            configured_keys_json=configuration, inventory_complete=True,
        )


@pytest.mark.parametrize(
    "identity_override",
    [
        {"image_id": 11},
        {"store_id": 3},
        {"external_system": "another-vault"},
        {"snapshot_id": "another-snapshot"},
    ],
)
def test_inventory_signature_is_bound_to_image_store_and_source_identity(identity_override):
    identity = {
        "image_id": 10,
        "store_id": 2,
        "external_system": "backup-vault",
        "snapshot_id": "snapshot-1",
        "generated_at": GENERATED_AT,
        "entries": ENTRIES,
        "inventory_complete": True,
    }
    signature = inventory_signature(**identity, secret=SECRET)
    altered_identity = {**identity, **identity_override}
    with pytest.raises(ValueError, match="signature is invalid"):
        verify_inventory_signature(
            **altered_identity,
            signature=signature,
            configured_keys_json=json.dumps({"backup-vault": SECRET, "another-vault": SECRET}),
        )
