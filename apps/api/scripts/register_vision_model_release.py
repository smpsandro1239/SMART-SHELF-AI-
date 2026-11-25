"""Register an Ed25519-verified ONNX release using the database owner principal."""
from __future__ import annotations

import os
import re

from sqlalchemy import text

from app.database import SessionLocal
from app.vision_model_manifest import ModelManifestError, verify_model_manifest
from app.vision_model_release import ModelReleaseError, register_model_release


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required to register a signed model release")
    return value


def _verify_migration_owner() -> None:
    with SessionLocal() as db:
        if db.get_bind().dialect.name != "postgresql":
            raise RuntimeError("Signed model release registration requires PostgreSQL")
        owner = db.execute(
            text(
                """
                SELECT pg_get_userbyid(relowner)
                FROM pg_class
                WHERE oid = 'public.vision_model_release_states'::regclass
                """
            )
        ).scalar_one_or_none()
        current_user = db.execute(text("SELECT current_user")).scalar_one()
        if owner is None or current_user != owner:
            raise RuntimeError(
                "Model releases must be registered by the PostgreSQL owner/migration principal"
            )


def main() -> None:
    deployment_id = _required("VISION_MODEL_DEPLOYMENT_ID")
    if os.getenv("APP_ENV", "development").strip().lower() == "production" and deployment_id == "default":
        raise RuntimeError("Production model release registration requires a stable non-default deployment ID")
    manifest_path = _required("VISION_MODEL_MANIFEST_PATH")
    trusted_keys = _required("VISION_MODEL_TRUSTED_KEYS_JSON")
    detector_path = _required("VISION_DETECTOR_MODEL_PATH")
    embedding_path = os.getenv("VISION_EMBEDDING_MODEL_PATH", "").strip() or None
    revoked_keys = os.getenv("VISION_MODEL_REVOKED_KEY_IDS_JSON", "[]")

    try:
        signed_release = verify_model_manifest(
            manifest_path,
            trusted_keys,
            detector_path,
            embedding_path,
            revoked_key_ids_json=revoked_keys,
        )
    except ModelManifestError as exc:
        raise RuntimeError(f"Signed ONNX model manifest verification failed: {exc}") from exc

    expected_digests = {
        "detector_sha256": _required("VISION_DETECTOR_MODEL_SHA256"),
        "embedding_sha256": os.getenv("VISION_EMBEDDING_MODEL_SHA256", "").strip() or None,
    }
    for field, expected in expected_digests.items():
        actual = signed_release[field]
        if expected is None:
            if actual is not None:
                raise RuntimeError(f"Signed model {field} is configured but its deployment digest is missing")
            continue
        if not _SHA256.fullmatch(expected) or expected != actual:
            raise RuntimeError(f"{field} does not match the signed model manifest")

    _verify_migration_owner()
    try:
        register_model_release(
            SessionLocal,
            deployment_id=deployment_id,
            model_release=signed_release,
        )
    except ModelReleaseError as exc:
        raise RuntimeError(f"Signed model release registration was rejected: {exc}") from exc

    print(
        "Registered verified ONNX model release: "
        f"deployment={deployment_id}, model={signed_release['model_id']}, "
        f"version={signed_release['release_version']}, key_id={signed_release['key_id']}."
    )


if __name__ == "__main__":
    main()
