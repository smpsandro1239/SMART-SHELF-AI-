"""Prove PostgreSQL holds artifact/source locks throughout synchronous provider reads.

The provider callback is deliberately a deterministic byte-returning stand-in:
this smoke test verifies transaction/lock lifetime, not connectivity to an
external storage vendor.
"""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from sqlalchemy import text

from app import models
from app.artifact_consumption import consume_external_artifact_bytes
from app.artifact_inventory_signing import canonical_inventory_payload, inventory_signature
from app.config import settings
from app.database import SessionLocal


def create_fixture(suffix: str, payload: bytes) -> tuple[int, int, int, int]:
    digest = sha256(payload).hexdigest()
    with SessionLocal() as db:
        store = models.Store(code=f"PG-ART-CONSUME-{suffix}", name="Artifact consume lock smoke")
        admin = models.User(
            email=f"pg-art-consume-{suffix}@example.test",
            full_name="Artifact consume smoke administrator",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        db.add_all([store, admin])
        db.flush()

        zone = models.Zone(store_id=store.id, name="Artifact consume zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"ART-CONSUME-{suffix}")
        db.add(shelf)
        db.flush()

        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="artifact-consume.jpg",
            storage_path=f"/tmp/artifact-consume-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=12,
            sha256="a" * 64,
            retention_status="ACTIVE",
            legal_hold=False,
        )
        db.add(image)
        db.flush()

        integration = models.StoreExternalIntegration(
            store_id=store.id,
            external_system="postgres-artifact-smoke",
            provider="deterministic-smoke-provider",
            status="ACTIVE",
            required_for_retention=True,
            capabilities=["READ"],
            created_by_user_id=admin.id,
            updated_by_user_id=admin.id,
        )
        artifact = models.ShelfImageArtifactReference(
            shelf_image_id=image.id,
            store_id=store.id,
            artifact_type="BACKUP",
            external_system="postgres-artifact-smoke",
            external_reference=f"smoke/{suffix}",
            sha256=digest,
            declared_by_user_id=admin.id,
        )
        db.add_all([integration, artifact])
        db.flush()

        snapshot_id = f"snapshot-{suffix}"
        generated_at = models.utc_now()
        manifest = [{
            "artifact_type": "BACKUP",
            "external_reference": f"smoke/{suffix}",
            "sha256": digest,
            "state": "PRESENT",
        }]
        signing_secret = "postgres-artifact-smoke-signing-secret-long-enough"
        signature = inventory_signature(
            image_id=image.id,
            store_id=store.id,
            external_system="postgres-artifact-smoke",
            snapshot_id=snapshot_id,
            generated_at=generated_at,
            entries=manifest,
            secret=signing_secret,
            inventory_complete=True,
        )
        manifest_digest = sha256(canonical_inventory_payload(
            image_id=image.id,
            store_id=store.id,
            external_system="postgres-artifact-smoke",
            snapshot_id=snapshot_id,
            generated_at=generated_at,
            entries=manifest,
            inventory_complete=True,
        )).hexdigest()
        db.add(models.ShelfImageArtifactInventorySnapshot(
            shelf_image_id=image.id,
            store_id=store.id,
            external_system="postgres-artifact-smoke",
            snapshot_id=snapshot_id,
            generated_at=generated_at,
            inventory_complete=True,
            manifest_sha256=manifest_digest,
            source_signature=signature,
            inventory_manifest=manifest,
            artifact_count=1,
            present_count=1,
            absent_count=0,
            created_by_user_id=admin.id,
        ))
        db.commit()
        return image.id, artifact.id, store.id, integration.id


def main() -> None:
    suffix = uuid4().hex[:8]
    payload = f"external artifact smoke payload {suffix}".encode()
    original_keys = settings.artifact_inventory_hmac_keys_json
    settings.artifact_inventory_hmac_keys_json = (
        '{"postgres-artifact-smoke":"postgres-artifact-smoke-signing-secret-long-enough"}'
    )
    try:
        image_id, artifact_id, store_id, integration_id = create_fixture(suffix, payload)

        app_name = f"ss-artifact-read-{suffix}"
        fetch_started = Event()
        allow_fetch_finish = Event()
        retention_started = Event()
        retention_finished = Event()
        integration_update_started = Event()
        integration_update_finished = Event()

        def dedicated_session():
            db = SessionLocal()
            db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": app_name},
            )
            return db

        def provider_fetch(_external_system: str, _external_reference: str) -> bytes:
            fetch_started.set()
            if not allow_fetch_finish.wait(timeout=15):
                raise TimeoutError("smoke provider read was not released")
            return payload

        def consume() -> bytes:
            return consume_external_artifact_bytes(
                image_id=image_id,
                artifact_id=artifact_id,
                store_id=store_id,
                fetch_bytes=provider_fetch,
                session_factory=dedicated_session,
            )

        def restrict_source() -> None:
            with SessionLocal() as db:
                db.execute(
                    text("SELECT set_config('application_name', :name, false)"),
                    {"name": f"{app_name}-retention"},
                )
                retention_started.set()
                image = (
                    db.query(models.ShelfImage)
                    .filter(models.ShelfImage.id == image_id)
                    .with_for_update()
                    .one()
                )
                image.retention_status = "RESTRICTED"
                image.retention_reason = "PostgreSQL artifact-consumption lock smoke"
                image.retention_requested_at = models.utc_now()
                db.commit()
                retention_finished.set()

        def revoke_integration() -> None:
            with SessionLocal() as db:
                db.execute(
                    text("SELECT set_config('application_name', :name, false)"),
                    {"name": f"{app_name}-integration"},
                )
                integration_update_started.set()
                integration = (
                    db.query(models.StoreExternalIntegration)
                    .filter(models.StoreExternalIntegration.id == integration_id)
                    .with_for_update()
                    .one()
                )
                integration.status = "REVOKED"
                integration.updated_at = models.utc_now()
                db.commit()
                integration_update_finished.set()

        with ThreadPoolExecutor(max_workers=3) as executor:
            consume_future = executor.submit(consume)
            assert fetch_started.wait(timeout=10), "provider callback did not start"
            retention_future = executor.submit(restrict_source)
            integration_future = executor.submit(revoke_integration)
            assert retention_started.wait(timeout=10), "retention transaction did not start"
            assert integration_update_started.wait(timeout=10), "integration revocation did not start"

            deadline = monotonic() + 10
            observed_blocker = False
            observed_integration_blocker = False
            while monotonic() < deadline:
                with SessionLocal() as monitor:
                    activity = monitor.execute(
                        text(
                            "SELECT wait_event_type, pg_blocking_pids(pid) "
                            "FROM pg_stat_activity WHERE application_name = :name"
                        ),
                        {"name": f"{app_name}-retention"},
                    ).first()
                if activity is not None and activity[0] == "Lock" and activity[1]:
                    observed_blocker = True
                with SessionLocal() as monitor:
                    integration_activity = monitor.execute(
                        text(
                            "SELECT wait_event_type, pg_blocking_pids(pid) "
                            "FROM pg_stat_activity WHERE application_name = :name"
                        ),
                        {"name": f"{app_name}-integration"},
                    ).first()
                if (
                    integration_activity is not None
                    and integration_activity[0] == "Lock"
                    and integration_activity[1]
                ):
                    observed_integration_blocker = True
                if observed_blocker and observed_integration_blocker:
                    break
                if retention_finished.is_set() or integration_update_finished.is_set():
                    break
                sleep(0.05)

            try:
                assert observed_blocker, (
                    "retention did not wait on the active artifact-consumption transaction"
                )
                assert observed_integration_blocker, (
                    "integration revocation did not wait on the active artifact-consumption transaction"
                )
                assert not retention_finished.is_set(), (
                    "retention completed while provider read still held source-image lock"
                )
                assert not integration_update_finished.is_set(), (
                    "integration revocation completed while provider read still held integration lock"
                )
            finally:
                allow_fetch_finish.set()

            assert consume_future.result(timeout=10) == payload
            retention_future.result(timeout=10)
            integration_future.result(timeout=10)

        assert retention_finished.is_set(), "retention did not resume after provider read"
        assert integration_update_finished.is_set(), "integration revocation did not resume after provider read"
        with SessionLocal() as db:
            integration = db.get(models.StoreExternalIntegration, integration_id)
            assert integration is not None and integration.status == "REVOKED"
        with SessionLocal() as db:
            image = db.get(models.ShelfImage, image_id)
            assert image is not None and image.retention_status == "RESTRICTED"

        # A mismatched store scope must be rejected before the provider callback.
        # This is exercised against PostgreSQL rather than the permissive unit-test
        # query doubles, which do not evaluate SQLAlchemy filter expressions.
        provider_calls = []
        try:
            consume_external_artifact_bytes(
                image_id=image_id,
                artifact_id=artifact_id,
                store_id=store_id + 1,
                fetch_bytes=lambda *args: provider_calls.append(args) or payload,
            )
        except LookupError:
            pass
        else:
            raise AssertionError("cross-store artifact consumption was not rejected")
        assert provider_calls == [], "provider was called for a cross-store request"
        settings.artifact_inventory_hmac_keys_json = original_keys

    finally:
        settings.artifact_inventory_hmac_keys_json = original_keys

if __name__ == "__main__":
    main()
