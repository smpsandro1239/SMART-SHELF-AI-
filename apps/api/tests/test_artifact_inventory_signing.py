from datetime import datetime, timedelta, timezone
import json

import pytest

from app.artifact_inventory_signing import (
    InventorySignatureConfigurationError,
    canonical_inventory_payload,
    inventory_signature,
    legacy_inventory_ingestion_is_allowed,
    verify_inventory_signature,
)


SECRET = "test-only-artifact-inventory-signing-key-not-for-deployment"
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
    with pytest.raises(InventorySignatureConfigurationError, match="duplicate identifier"):
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

def _scoped_keyring(store_id=2):
    return json.dumps({
        "stores": {
            str(store_id): {
                "backup-vault": {
                    "active_key_id": "key-2026-02",
                    "keys": {
                        "key-2026-01": "previous-store-specific-secret-with-32-bytes",
                        "key-2026-02": "current-store-specific-secret-with-32-bytes",
                    },
                }
            }
        }
    })


def test_store_scoped_keyring_binds_signature_to_store_and_key_id():
    keyring = _scoped_keyring()
    signature = inventory_signature(
        image_id=10,
        store_id=2,
        external_system="backup-vault",
        snapshot_id="snapshot-scoped",
        generated_at=GENERATED_AT,
        entries=ENTRIES,
        secret="current-store-specific-secret-with-32-bytes",
        inventory_complete=True,
        key_id="key-2026-02",
    )
    digest = verify_inventory_signature(
        image_id=10,
        store_id=2,
        external_system="backup-vault",
        snapshot_id="snapshot-scoped",
        generated_at=GENERATED_AT,
        entries=ENTRIES,
        signature=signature,
        configured_keys_json=keyring,
        inventory_complete=True,
        key_id="key-2026-02",
        require_active_key=True,
    )
    assert len(digest) == 64

    with pytest.raises(InventorySignatureConfigurationError, match="not configured"):
        verify_inventory_signature(
            image_id=10,
            store_id=3,
            external_system="backup-vault",
            snapshot_id="snapshot-scoped",
            generated_at=GENERATED_AT,
            entries=ENTRIES,
            signature=signature,
            configured_keys_json=keyring,
            inventory_complete=True,
            key_id="key-2026-02",
        )


def test_key_rotation_keeps_old_snapshots_verifiable_but_rejects_new_old_key_signatures():
    keyring = _scoped_keyring()
    old_signature = inventory_signature(
        image_id=10,
        store_id=2,
        external_system="backup-vault",
        snapshot_id="snapshot-before-rotation",
        generated_at=GENERATED_AT,
        entries=ENTRIES,
        secret="previous-store-specific-secret-with-32-bytes",
        inventory_complete=True,
        key_id="key-2026-01",
    )

    # Historical snapshots may use a retained, non-active key.
    assert verify_inventory_signature(
        image_id=10,
        store_id=2,
        external_system="backup-vault",
        snapshot_id="snapshot-before-rotation",
        generated_at=GENERATED_AT,
        entries=ENTRIES,
        signature=old_signature,
        configured_keys_json=keyring,
        inventory_complete=True,
        key_id="key-2026-01",
        require_active_key=False,
    )

    # New ingestion must use the current key, even if an old key remains
    # available solely for historical verification.
    with pytest.raises(InventorySignatureConfigurationError, match="active key"):
        verify_inventory_signature(
            image_id=10,
            store_id=2,
            external_system="backup-vault",
            snapshot_id="snapshot-after-rotation",
            generated_at=GENERATED_AT,
            entries=ENTRIES,
            signature=old_signature,
            configured_keys_json=keyring,
            inventory_complete=True,
            key_id="key-2026-01",
            require_active_key=True,
        )


def test_key_id_is_part_of_the_canonical_signed_payload():
    first = canonical_inventory_payload(
        image_id=10, store_id=2, external_system="backup-vault",
        snapshot_id="snapshot-key-id", generated_at=GENERATED_AT,
        entries=ENTRIES, inventory_complete=True, key_id="key-a",
    )
    second = canonical_inventory_payload(
        image_id=10, store_id=2, external_system="backup-vault",
        snapshot_id="snapshot-key-id", generated_at=GENERATED_AT,
        entries=ENTRIES, inventory_complete=True, key_id="key-b",
    )
    assert first != second


def test_scoped_keyring_rejects_missing_active_key_and_weak_secret():
    invalid = json.dumps({
        "stores": {
            "2": {
                "backup-vault": {
                    "active_key_id": "missing",
                    "keys": {"key-old": "short"},
                }
            }
        }
    })
    with pytest.raises(InventorySignatureConfigurationError):
        verify_inventory_signature(
            image_id=10, store_id=2, external_system="backup-vault",
            snapshot_id="snapshot-invalid-keyring", generated_at=GENERATED_AT,
            entries=ENTRIES, signature="a" * 64,
            configured_keys_json=invalid, inventory_complete=True,
            key_id="key-old",
        )



@pytest.mark.parametrize(
    "app_env, override, expected",
    [
        ("production", None, False),
        ("Production", None, False),
        ("development", None, True),
        ("test", None, True),
        ("production", True, True),
        ("development", False, False),
    ],
)
def test_legacy_ingestion_cutover_policy(app_env, override, expected):
    assert legacy_inventory_ingestion_is_allowed(
        app_env=app_env,
        configured_override=override,
    ) is expected
