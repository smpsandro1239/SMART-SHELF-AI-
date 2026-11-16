"""Canonical signing helpers for trusted external artifact inventory snapshots."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from typing import Any


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class InventorySignatureConfigurationError(ValueError):
    """Raised when a source has no valid server-side HMAC key."""


def _utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Inventory generated_at must include a timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def canonical_inventory_payload(
    *,
    image_id: int,
    store_id: int,
    external_system: str,
    snapshot_id: str,
    generated_at: datetime,
    entries: list[dict[str, Any]],
    inventory_complete: bool,
) -> bytes:
    """Return deterministic UTF-8 bytes signed by the trusted source connector."""
    if inventory_complete is not True:
        raise ValueError("Source must explicitly attest complete inventory coverage")
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
        "schema_version": 1,
        "image_id": int(image_id),
        "store_id": int(store_id),
        "external_system": external_system.strip(),
        "snapshot_id": snapshot_id.strip(),
        "generated_at": _utc_timestamp(generated_at),
        "inventory_complete": True,
        "entries": normalized_entries,
    }
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
    inventory_complete: bool = True,
) -> str:
    """Create a lowercase SHA-256 HMAC for connector-side tests and integrations."""
    if len(secret.encode("utf-8")) < 32:
        raise InventorySignatureConfigurationError("Inventory HMAC secrets must contain at least 32 UTF-8 bytes")
    canonical = canonical_inventory_payload(
        image_id=image_id,
        store_id=store_id,
        external_system=external_system,
        snapshot_id=snapshot_id,
        generated_at=generated_at,
        entries=entries,
        inventory_complete=inventory_complete,
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
    inventory_complete: bool = True,
) -> str:
    """Verify a source signature and return the canonical manifest SHA-256."""
    try:
        keys = json.loads(configured_keys_json or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise InventorySignatureConfigurationError("Inventory HMAC key configuration must be a JSON object") from exc
    if not isinstance(keys, dict):
        raise InventorySignatureConfigurationError("Inventory HMAC key configuration must be a JSON object")
    secret = keys.get(external_system)
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < 32:
        raise InventorySignatureConfigurationError(
            f"No valid inventory HMAC key is configured for source '{external_system}'"
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
    )
    expected = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("External artifact inventory signature is invalid")
    return hashlib.sha256(canonical).hexdigest()
