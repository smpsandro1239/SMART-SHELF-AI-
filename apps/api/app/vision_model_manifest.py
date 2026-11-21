"""Verify signed ONNX model manifests against an explicit Ed25519 trust store."""
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
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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


def verify_model_manifest(
    manifest_path: str | Path,
    trusted_keys_json: str,
    detector_path: str | Path,
    embedding_path: str | Path | None = None,
) -> dict[str, str | None]:
    """Verify the Ed25519 signature and bind manifest digests to exact model files.

    The detached signature is over canonical UTF-8 JSON of the complete payload.
    Trusted public keys are supplied as JSON: {"key-id": "<base64 raw Ed25519 key>"}.
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

    try:
        envelope = json.loads(raw_manifest.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ModelManifestError("Model manifest must be valid UTF-8 JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise ModelManifestError("Manifest envelope must contain exactly payload and signature")

    payload = envelope["payload"]
    required_fields = {"schema_version", "key_id", "detector_sha256", "embedding_sha256"}
    if not isinstance(payload, dict) or set(payload) != required_fields:
        raise ModelManifestError("Manifest payload has missing or unsupported fields")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ModelManifestError("Unsupported model manifest schema_version")
    key_id = payload["key_id"]
    if not isinstance(key_id, str) or not _KEY_ID.fullmatch(key_id):
        raise ModelManifestError("Manifest key_id is invalid")
    if key_id not in keyring:
        raise ModelManifestError("Manifest was signed by an untrusted key_id")

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
        "detector_sha256": detector_digest,
        "embedding_sha256": embedding_digest,
    }
