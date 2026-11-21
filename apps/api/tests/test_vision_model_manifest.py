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


def test_real_provider_factory_rejects_missing_signed_manifest_even_with_matching_sha(tmp_path, monkeypatch):
    detector = tmp_path / "detector.onnx"
    detector.write_bytes(b"detector")
    monkeypatch.setenv("VISION_DETECTOR_MODEL_PATH", str(detector))
    monkeypatch.setenv("VISION_DETECTOR_MODEL_SHA256", __import__("hashlib").sha256(b"detector").hexdigest())
    monkeypatch.setenv("VISION_CLASS_LABELS_JSON", '{"0":"product"}')
    monkeypatch.delenv("VISION_EMBEDDING_MODEL_PATH", raising=False)
    monkeypatch.delenv("VISION_MODEL_MANIFEST_PATH", raising=False)
    monkeypatch.setenv("VISION_MODEL_TRUSTED_KEYS_JSON", '{"release-2026":"unused"}')

    from app.vision_onnx import ONNXConfigurationError, create_provider

    with pytest.raises(ONNXConfigurationError, match="VISION_MODEL_MANIFEST_PATH is required"):
        create_provider()


def test_real_provider_factory_loads_only_after_signed_manifest_and_sha_match(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace

    manifest, keyring, detector, embedding, payload = signed_manifest(tmp_path)
    monkeypatch.setenv("VISION_DETECTOR_MODEL_PATH", str(detector))
    monkeypatch.setenv("VISION_DETECTOR_MODEL_SHA256", payload["detector_sha256"])
    monkeypatch.setenv("VISION_CLASS_LABELS_JSON", '{"0":"product"}')
    monkeypatch.setenv("VISION_MODEL_MANIFEST_PATH", str(manifest))
    monkeypatch.setenv("VISION_MODEL_TRUSTED_KEYS_JSON", keyring)
    monkeypatch.delenv("VISION_EMBEDDING_MODEL_PATH", raising=False)
    monkeypatch.delenv("VISION_EMBEDDING_MODEL_SHA256", raising=False)
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        SimpleNamespace(InferenceSession=lambda *args, **kwargs: SimpleNamespace(
            get_inputs=lambda: [SimpleNamespace(name="images", type="tensor(float)", shape=[1, 3, 640, 640])],
            get_outputs=lambda: [SimpleNamespace(name="detections", type="tensor(float)", shape=[1, "n", 6])],
        )),
    )

    from app.vision_onnx import create_provider

    provider = create_provider()

    assert provider.detector_sha256 == payload["detector_sha256"]
    assert provider.embedding_path is None


def test_offline_signing_utility_creates_verifiable_manifest(tmp_path):
    from scripts.create_vision_model_manifest import build_manifest

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    detector = tmp_path / "detector.onnx"
    detector.write_bytes(b"release-candidate-detector")
    manifest_path = tmp_path / "manifest.json"
    envelope = build_manifest(private_key, "release-candidate", detector)
    manifest_path.write_text(json.dumps(envelope), encoding="utf-8")
    keyring = json.dumps({
        "release-candidate": base64.b64encode(public_key).decode("ascii"),
    })

    verified = verify_model_manifest(manifest_path, keyring, detector)

    assert verified["key_id"] == "release-candidate"
    assert verified["detector_sha256"] == envelope["payload"]["detector_sha256"]
