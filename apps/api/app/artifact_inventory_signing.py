"""Canonical signing helpers for trusted external artifact inventory snapshots.

Version 1 snapshots retain their historical source-wide key lookup. Version 2
snapshots bind a key identifier into the signed canonical payload and resolve
keys inside a store + external-system namespace.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class InventorySignatureConfigurationError(ValueError):
    """Raised when a source has no valid server-side HMAC key."""


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Inventory generated_at must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _validate_key_id(key_id: str) -> str:
    if not isinstance(key_id, str) or not _KEY_ID_RE.fullmatch(key_id):
        raise ValueError("Inventory key_id must be 1-64 safe identifier characters")
    return key_id


def _parse_key_configuration(configured_keys_json: str) -> dict[str, Any]:
    def reject_duplicate_keys(pairs):
        parsed = {}
        for key, value in pairs:
            if key in parsed:
                raise InventorySignatureConfigurationError(
                    "Inventory HMAC key configuration contains a duplicate identifier"
                )
            parsed[key] = value
        return parsed

    try:
        configuration = json.loads(
            configured_keys_json or "{}",
            object_pairs_hook=reject_duplicate_keys,
        )
    except InventorySignatureConfigurationError:
        raise
    except (TypeError, json.JSONDecodeError) as exc:
        raise InventorySignatureConfigurationError(
            "Inventory HMAC key configuration must be a JSON object"
        ) from exc
    if not isinstance(configuration, dict):
        raise InventorySignatureConfigurationError(
            "Inventory HMAC key configuration must be a JSON object"
        )
    return configuration


def _valid_secret(secret: Any) -> bool:
    return isinstance(secret, str) and len(secret.encode("utf-8")) >= 32


def resolve_inventory_secret(
    *,
    configured_keys_json: str,
    store_id: int,
    external_system: str,
    key_id: str,
    require_active: bool = False,
) -> str:
    """Resolve a key without crossing store/source namespaces.

    Legacy v1 snapshots use the historical flat mapping
    {"external-system": "secret"}. New v2 snapshots use:
    {"stores": {"<store-id>": {"<external-system>": {
        "active_key_id": "key-2026-02",
        "keys": {"key-2026-01": "old-secret", "key-2026-02": "new-secret"}
    }}}}
    """
    configuration = _parse_key_configuration(configured_keys_json)
    if key_id == "legacy":
        secret = configuration.get(external_system)
        if not _valid_secret(secret):
            raise InventorySignatureConfigurationError(
                f"No valid legacy inventory HMAC key is configured for source '{external_system}'"
            )
        return secret

    _validate_key_id(key_id)
    stores = configuration.get("stores")
    store_config = stores.get(str(store_id)) if isinstance(stores, dict) else None
    source_config = store_config.get(external_system) if isinstance(store_config, dict) else None
    if not isinstance(source_config, dict):
        raise InventorySignatureConfigurationError(
            f"No inventory HMAC keyring is configured for store {store_id} and source '{external_system}'"
        )
    active_key_id = source_config.get("active_key_id")
    keys = source_config.get("keys")
    if not isinstance(active_key_id, str) or not _KEY_ID_RE.fullmatch(active_key_id):
        raise InventorySignatureConfigurationError("Inventory keyring active_key_id is invalid")
    if require_active and key_id != active_key_id:
        raise InventorySignatureConfigurationError(
            "Inventory snapshot must be signed with the active key for this store and source"
        )
    secret = keys.get(key_id) if isinstance(keys, dict) else None
    if not _valid_secret(secret):
        raise InventorySignatureConfigurationError(
            f"Inventory HMAC key '{key_id}' is not configured for store {store_id} and source '{external_system}'"
        )
    return secret


def canonical_inventory_payload(
    *,
    image_id: int,
    store_id: int,
    external_system: str,
    snapshot_id: str,
    generated_at: datetime,
    entries: list[dict[str, Any]],
    inventory_complete: bool,
    key_id: str = "legacy",
) -> bytes:
    """Return deterministic UTF-8 bytes signed by the trusted source connector."""
    if inventory_complete is not True:
        raise ValueError("Source must explicitly attest complete inventory coverage")
    if key_id != "legacy":
        _validate_key_id(key_id)
    normalized_entries = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        artifact_type = str(entry["artifact_type"]).strip()
        external_reference = str(entry["external_reference"]).strip()
        state = str(entry["state"]).upper()
        sha256 = entry.get("sha256")
        if not artifact_type or not external_reference:
            raise ValueError("Inventory entries require artifact_type and external_reference")
        if state not in {"PRESENT", "ABSENT"}:
            raise ValueError("Inventory entry state must be PRESENT or ABSENT")
        if sha256 is not None and not _SHA256_RE.fullmatch(str(sha256)):
            raise ValueError("Inventory entry SHA-256 must be lowercase hexadecimal")
        identity = (artifact_type, external_reference)
        if identity in seen:
            raise ValueError("Inventory entries cannot contain duplicate artifact identities")
        seen.add(identity)
        normalized_entries.append({
            "artifact_type": artifact_type,
            "external_reference": external_reference,
            "sha256": sha256,
            "state": state,
        })

    normalized_entries.sort(key=lambda item: (item["artifact_type"], item["external_reference"]))
    payload = {
        "schema_version": 1 if key_id == "legacy" else 2,
        "image_id": int(image_id),
        "store_id": int(store_id),
        "external_system": external_system.strip(),
        "snapshot_id": snapshot_id.strip(),
        "generated_at": _utc_timestamp(generated_at),
        "inventory_complete": True,
        "entries": normalized_entries,
    }
    if key_id != "legacy":
        payload["key_id"] = key_id
    if payload["image_id"] <= 0 or payload["store_id"] <= 0:
        raise ValueError("Inventory image_id and store_id must be positive")
    if not payload["external_system"] or not payload["snapshot_id"]:
        raise ValueError("Inventory source and snapshot identifiers are required")
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def inventory_signature(
    *,
    image_id: int,
    store_id: int,
    external_system: str,
    snapshot_id: str,
    generated_at: datetime,
    entries: list[dict[str, Any]],
    secret: str,
    inventory_complete: bool,
    key_id: str = "legacy",
) -> str:
    """Create a lowercase SHA-256 HMAC for connector-side tests and integrations."""
    if not _valid_secret(secret):
        raise InventorySignatureConfigurationError(
            "Inventory HMAC secrets must contain at least 32 UTF-8 bytes"
        )
    canonical = canonical_inventory_payload(
        image_id=image_id,
        store_id=store_id,
        external_system=external_system,
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        entries=entries,
        inventory_complete=inventory_complete,
        key_id=key_id,
    )
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def verify_inventory_signature(
    *,
    image_id: int,
    store_id: int,
    external_system: str,
    snapshot_id: str,
    generated_at: datetime,
    entries: list[dict[str, Any]],
    signature: str,
    configured_keys_json: str,
    inventory_complete: bool,
    key_id: str = "legacy",
    require_active_key: bool = False,
) -> str:
    """Verify a source signature and return the canonical manifest SHA-256."""
    secret = resolve_inventory_secret(
        configured_keys_json=configured_keys_json,
        store_id=store_id,
        external_system=external_system,
        key_id=key_id,
        require_active=require_active_key,
    )
    if not isinstance(signature, str) or not _SHA256_RE.fullmatch(signature):
        raise ValueError("Inventory signature must be a lowercase SHA-256 HMAC")
    canonical = canonical_inventory_payload(
        image_id=image_id,
        store_id=store_id,
        external_system=external_system,
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        entries=entries,
        inventory_complete=inventory_complete,
        key_id=key_id,
    )
    expected = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("External artifact inventory signature is invalid")
    return hashlib.sha256(canonical).hexdigest()


def verify_inventory_snapshot_record(
    *,
    snapshot: Any,
    expected_references: list[Any],
    configured_keys_json: str,
) -> bool:
    """Revalidate a persisted snapshot before it can authorize artifact access."""
    try:
        manifest = snapshot.inventory_manifest
        if not isinstance(manifest, list) or not manifest:
            return False
        if not all(isinstance(entry, dict) for entry in manifest):
            return False
        if snapshot.inventory_complete is not True:
            return False
        if snapshot.artifact_count != len(manifest):
            return False
        if snapshot.present_count != sum(entry.get("state") == "PRESENT" for entry in manifest):
            return False
        if snapshot.absent_count != sum(entry.get("state") == "ABSENT" for entry in manifest):
            return False

        expected = {
            (reference.artifact_type, reference.external_reference, reference.sha256)
            for reference in expected_references
        }
        actual = {
            (entry.get("artifact_type"), entry.get("external_reference"), entry.get("sha256"))
            for entry in manifest
        }
        if len(expected) != len(expected_references) or len(actual) != len(manifest):
            return False
        if actual != expected:
            return False

        # SQLite drops timezone metadata from DateTime(timezone=True).
        generated_at = snapshot.generated_at
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)

        key_id = getattr(snapshot, "key_id", "legacy") or "legacy"
        digest = verify_inventory_signature(
            image_id=snapshot.shelf_image_id,
            store_id=snapshot.store_id,
            external_system=snapshot.external_system,
            snapshot_id=snapshot.snapshot_id,
            generated_at=generated_at,
            entries=manifest,
            signature=snapshot.source_signature,
            configured_keys_json=configured_keys_json,
            inventory_complete=snapshot.inventory_complete,
            key_id=key_id,
        )
        return hmac.compare_digest(digest, snapshot.manifest_sha256)
    except (AttributeError, InventorySignatureConfigurationError, KeyError, TypeError, ValueError):
        return False
