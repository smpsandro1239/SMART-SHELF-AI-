"""Create an Ed25519-signed manifest for approved ONNX model artifacts.

Run this tool in the controlled release environment. The private key must never
be copied into the repository, Docker image, runtime environment, or model volume.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import re
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def build_manifest(
    private_key: Ed25519PrivateKey,
    key_id: str,
    detector_path: Path,
    embedding_path: Path | None = None,
) -> dict:
    if not _KEY_ID.fullmatch(key_id):
        raise ValueError("key_id must contain 1-64 safe ASCII characters")
    if detector_path.is_symlink() or not detector_path.is_file():
        raise ValueError("detector must be a regular non-symlink file")
    if embedding_path is not None and (embedding_path.is_symlink() or not embedding_path.is_file()):
        raise ValueError("embedding model must be a regular non-symlink file")
    payload = {
        "schema_version": 1,
        "key_id": key_id,
        "detector_sha256": _sha256(detector_path),
        "embedding_sha256": _sha256(embedding_path) if embedding_path is not None else None,
    }
    signature = private_key.sign(_canonical_json(payload))
    import base64

    return {
        "payload": payload,
        "signature": base64.b64encode(signature).decode("ascii"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--private-key-pem", required=True, type=Path)
    parser.add_argument("--detector", required=True, type=Path)
    parser.add_argument("--embedding", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.private_key_pem.is_symlink() or not args.private_key_pem.is_file():
        parser.error("--private-key-pem must point to a regular non-symlink file")
    key_bytes = args.private_key_pem.read_bytes()
    try:
        private_key = serialization.load_pem_private_key(key_bytes, password=None)
    except TypeError:
        password = getpass.getpass("Private-key passphrase: ").encode("utf-8")
        private_key = serialization.load_pem_private_key(key_bytes, password=password)
    if not isinstance(private_key, Ed25519PrivateKey):
        parser.error("The supplied PEM key is not an Ed25519 private key")

    if args.output.exists() and args.output.is_symlink():
        parser.error("--output must not be a symbolic link")
    manifest = build_manifest(private_key, args.key_id, args.detector, args.embedding)
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    import base64

    print(f"Trusted public key for {args.key_id}: {base64.b64encode(public_bytes).decode('ascii')}")
    args.output.write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Signed model manifest written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
