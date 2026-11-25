"""Verify signed, versioned ONNX model manifests against an explicit Ed25519 trust store."""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Any


class ModelManifestError(ValueError):
    """Raised when a model manifest cannot be authenticated or matched to its files."""


_MAX_MANIFEST_BYTES = 64 * 1024
_MAX_TRUSTED_KEYS_BYTES = 16 * 1024
_MAX_TRUSTED_KEYS = 32
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_MAX_RELEASE_VERSION = 2**31 - 1


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModelManifestError("JSON objects must not contain duplicate keys")
        result[key] = value
    return result


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")


def _decode_base64(value: Any, label: str) -> bytes:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ModelManifestError(f"{label} must be a non-empty base64 string")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ModelManifestError(f"{label} is not valid base64") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ModelManifestError(f"Cannot read model file: {path.name}") from exc
    return digest.hexdigest()


def _parse_revoked_key_ids(raw: str | None) -> set[str]:
    if raw is None or not raw.strip():
        return set()
    try:
        revoked = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ModelManifestError("VISION_MODEL_REVOKED_KEY_IDS_JSON must be a JSON array") from exc
    if not isinstance(revoked, list) or len(revoked) > _MAX_TRUSTED_KEYS:
        raise ModelManifestError("Revoked key IDs must be a JSON array with at most 32 entries")
    if any(not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id) for key_id in revoked):
        raise ModelManifestError("Revoked key IDs contain an invalid identifier")
    if len(set(revoked)) != len(revoked):
        raise ModelManifestError("Revoked key IDs must not contain duplicates")
    return set(revoked)


def verify_model_manifest(
    manifest_path: str | Path,
    trusted_keys_json: str,
    detector_path: str | Path,
    embedding_path: str | Path | None = None,
    *,
    revoked_key_ids_json: str | None = None,
) -> dict[str, str | int | None]:
    """Verify Ed25519 signature and bind release identity to exact model bytes.

    The signature covers canonical UTF-8 JSON of the complete schema-v2 payload.
    Trusted public keys are supplied as {"key-id": "<base64 raw Ed25519 key>"}.
    """
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise ModelManifestError("The cryptography package is required to verify Ed25519 model manifests") from exc

    path = Path(manifest_path)
    if path.is_symlink() or not path.is_file():
        raise ModelManifestError("VISION_MODEL_MANIFEST_PATH must point to a regular, non-symlink file")
    try:
        if path.stat().st_size > _MAX_MANIFEST_BYTES:
            raise ModelManifestError("Model manifest exceeds the 64 KiB limit")
        raw_manifest = path.read_bytes()
    except OSError as exc:
        raise ModelManifestError("Cannot read model manifest") from exc

    if not isinstance(trusted_keys_json, str) or not trusted_keys_json.strip():
        raise ModelManifestError("VISION_MODEL_TRUSTED_KEYS_JSON is required")
    if len(trusted_keys_json.encode("utf-8")) > _MAX_TRUSTED_KEYS_BYTES:
        raise ModelManifestError("Trusted public key configuration exceeds the 16 KiB limit")
    try:
        keyring = json.loads(trusted_keys_json, object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ModelManifestError("VISION_MODEL_TRUSTED_KEYS_JSON must be valid JSON") from exc
    if not isinstance(keyring, dict) or not 1 <= len(keyring) <= _MAX_TRUSTED_KEYS:
        raise ModelManifestError("Trusted keyring must contain between 1 and 32 public keys")
    if any(not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id) for key_id in keyring):
        raise ModelManifestError("Trusted keyring contains an invalid key_id")
    revoked_key_ids = _parse_revoked_key_ids(revoked_key_ids_json)

    try:
        envelope = json.loads(raw_manifest.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ModelManifestError("Model manifest must be valid UTF-8 JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise ModelManifestError("Manifest envelope must contain exactly payload and signature")

    payload = envelope["payload"]
    required_fields = {
        "schema_version", "key_id", "model_id", "release_version",
        "detector_sha256", "embedding_sha256",
    }
    if not isinstance(payload, dict) or set(payload) != required_fields:
        raise ModelManifestError("Manifest payload has missing or unsupported fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 2:
        raise ModelManifestError("Unsupported model manifest schema_version; schema version 2 is required")

    key_id = payload["key_id"]
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ModelManifestError("Manifest key_id is invalid")
    if key_id in revoked_key_ids:
        raise ModelManifestError("Manifest signing key_id is explicitly revoked")
    if key_id not in keyring:
        raise ModelManifestError("Manifest was signed by an untrusted key_id")

    model_id = payload["model_id"]
    if not isinstance(model_id, str) or not _MODEL_ID.fullmatch(model_id):
        raise ModelManifestError("Manifest model_id is invalid")
    release_version = payload["release_version"]
    if (
        type(release_version) is not int
        or not 1 <= release_version <= _MAX_RELEASE_VERSION
    ):
        raise ModelManifestError("Manifest release_version must be a positive 32-bit integer")

    detector_digest = payload["detector_sha256"]
    embedding_digest = payload["embedding_sha256"]
    if not isinstance(detector_digest, str) or not _SHA256.fullmatch(detector_digest):
        raise ModelManifestError("Manifest detector_sha256 must be lowercase SHA-256 hex")
    if embedding_digest is not None and (
        not isinstance(embedding_digest, str) or not _SHA256.fullmatch(embedding_digest)
    ):
        raise ModelManifestError("Manifest embedding_sha256 must be null or lowercase SHA-256 hex")
    if (embedding_path is None) != (embedding_digest is None):
        raise ModelManifestError("Manifest embedding model entry must match VISION_EMBEDDING_MODEL_PATH")

    public_key_bytes = _decode_base64(keyring[key_id], "Trusted Ed25519 public key")
    if len(public_key_bytes) != 32:
        raise ModelManifestError("Trusted Ed25519 public keys must be exactly 32 bytes")
    signature = _decode_base64(envelope["signature"], "Manifest signature")
    if len(signature) != 64:
        raise ModelManifestError("Ed25519 signatures must be exactly 64 bytes")
    try:
        Ed25519PublicKey.from_public_bytes(public_key_bytes).verify(signature, _canonical_json(payload))
    except (InvalidSignature, ValueError) as exc:
        raise ModelManifestError("Model manifest Ed25519 signature is invalid") from exc

    detector = Path(detector_path)
    embedder = Path(embedding_path) if embedding_path is not None else None
    if detector.is_symlink() or (embedder is not None and embedder.is_symlink()):
        raise ModelManifestError("Model paths must not be symbolic links")
    if _sha256(detector) != detector_digest:
        raise ModelManifestError("Detector model SHA-256 does not match signed manifest")
    if embedder is not None and _sha256(embedder) != embedding_digest:
        raise ModelManifestError("Embedding model SHA-256 does not match signed manifest")

    return {
        "key_id": key_id,
        "model_id": model_id,
        "release_version": release_version,
        "manifest_sha256": hashlib.sha256(_canonical_json(payload)).hexdigest(),
        "detector_sha256": detector_digest,
        "embedding_sha256": embedding_digest,
    }
