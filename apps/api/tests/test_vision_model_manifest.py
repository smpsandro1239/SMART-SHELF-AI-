import base64
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.vision_model_manifest import ModelManifestError, _canonical_json, verify_model_manifest


def signed_manifest(tmp_path, *, detector_bytes=b"detector-v1", embedding_bytes=None, key_id="release-2026"):
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    detector = tmp_path / "detector.onnx"
    detector.write_bytes(detector_bytes)
    embedding = None
    if embedding_bytes is not None:
        embedding = tmp_path / "embedding.onnx"
        embedding.write_bytes(embedding_bytes)
    payload = {
        "schema_version": 1,
        "key_id": key_id,
        "detector_sha256": __import__("hashlib").sha256(detector_bytes).hexdigest(),
        "embedding_sha256": (
            __import__("hashlib").sha256(embedding_bytes).hexdigest()
            if embedding_bytes is not None else None
        ),
    }
    signature = private_key.sign(_canonical_json(payload))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }), encoding="utf-8")
    keyring = json.dumps({key_id: base64.b64encode(public_key).decode("ascii")})
    return manifest, keyring, detector, embedding, payload


def test_signed_manifest_accepts_trusted_ed25519_signature_and_exact_model_hashes(tmp_path):
    manifest, keyring, detector, embedding, payload = signed_manifest(
        tmp_path, embedding_bytes=b"embedder-v1"
    )

    result = verify_model_manifest(manifest, keyring, detector, embedding)

    assert result == {
        "key_id": "release-2026",
        "detector_sha256": payload["detector_sha256"],
        "embedding_sha256": payload["embedding_sha256"],
    }


def test_signed_manifest_rejects_unknown_key_id(tmp_path):
    manifest, keyring, detector, embedding, _ = signed_manifest(tmp_path)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["payload"]["key_id"] = "unknown-key"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ModelManifestError, match="untrusted key_id"):
        verify_model_manifest(manifest, keyring, detector, embedding)


def test_signed_manifest_rejects_invalid_signature(tmp_path):
    manifest, keyring, detector, embedding, _ = signed_manifest(tmp_path)
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_data["signature"] = base64.b64encode(b"x" * 64).decode("ascii")
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ModelManifestError, match="signature is invalid"):
        verify_model_manifest(manifest, keyring, detector, embedding)


def test_signed_manifest_rejects_model_changed_after_signing(tmp_path):
    manifest, keyring, detector, embedding, _ = signed_manifest(tmp_path)
    detector.write_bytes(b"tampered-model")

    with pytest.raises(ModelManifestError, match="does not match signed manifest"):
        verify_model_manifest(manifest, keyring, detector, embedding)


def test_signed_manifest_rejects_wrong_embedding_digest(tmp_path):
    manifest, keyring, detector, embedding, _ = signed_manifest(
        tmp_path, embedding_bytes=b"embedder-v1"
    )
    embedding.write_bytes(b"other-embedder")

    with pytest.raises(ModelManifestError, match="Embedding model SHA-256"):
        verify_model_manifest(manifest, keyring, detector, embedding)


def test_signed_manifest_requires_embedding_entry_to_match_runtime_configuration(tmp_path):
    manifest, keyring, detector, _, _ = signed_manifest(tmp_path)

    with pytest.raises(ModelManifestError, match="entry must match"):
        verify_model_manifest(manifest, keyring, detector, tmp_path / "unexpected.onnx")


@pytest.mark.parametrize(
    "raw_manifest",
    [
        b"{",
        b'{"payload":{"schema_version":1,"schema_version":1},"signature":"AA=="}',
        b'{"payload":{},"signature":"AA==","extra":true}',
    ],
)
def test_signed_manifest_rejects_malformed_or_ambiguous_json(tmp_path, raw_manifest):
    manifest, keyring, detector, embedding, _ = signed_manifest(tmp_path)
    manifest.write_bytes(raw_manifest)

    with pytest.raises(ModelManifestError):
        verify_model_manifest(manifest, keyring, detector, embedding)


def test_signed_manifest_rejects_untrusted_or_malformed_keyring(tmp_path):
    manifest, _, detector, embedding, _ = signed_manifest(tmp_path)

    with pytest.raises(ModelManifestError, match="required"):
        verify_model_manifest(manifest, "", detector, embedding)
    with pytest.raises(ModelManifestError, match="between 1 and 32"):
        verify_model_manifest(manifest, "{}", detector, embedding)
    with pytest.raises(ModelManifestError, match="exactly 32 bytes"):
        verify_model_manifest(
            manifest,
            json.dumps({"release-2026": base64.b64encode(b"short").decode("ascii")}),
            detector,
            embedding,
        )
