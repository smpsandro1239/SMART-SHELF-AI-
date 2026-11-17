"""Prove PostgreSQL serializes human detection review with image retention.

The real review endpoint must wait for the source ShelfImage row lock and
re-check retention state after the competing transaction commits. A restricted
image must not receive a new DetectionSkuReview.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def create_fixture(suffix: str) -> tuple[int, int, int]:
    with SessionLocal() as db:
        store = models.Store(
            code=f"PG-REVIEW-RETENTION-{suffix}",
            name="PostgreSQL human review retention smoke",
        )
        db.add(store)
        db.flush()
        supervisor = models.User(
            email=f"pg-human-review-{suffix}@example.test",
            full_name="Human review retention smoke supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store.id,
            is_active=True,
        )
        db.add(supervisor)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Human review retention zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PG-HUMAN-REVIEW-{suffix}")
        db.add(shelf)
        db.flush()
        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="human-review-retention-smoke.jpg",
            storage_path=f"/tmp/human-review-retention-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="e" * 64,
            analysis_status="COMPLETED",
            model_version="mock-human-review-retention-v1",
            retention_status="ACTIVE",
        )
        db.add(image)
        db.flush()
        detection = models.ShelfImageDetection(
            shelf_image_id=image.id,
            label="product",
            confidence=0.95,
            x_min=0.1,
            y_min=0.1,
            x_max=0.8,
            y_max=0.9,
            model_version="mock-human-review-retention-v1",
        )
        db.add(detection)
        db.commit()
        return image.id, detection.id, supervisor.id


def main() -> None:
    suffix = uuid4().hex[:10]
    image_id, detection_id, supervisor_id = create_fixture(suffix)
    application_name = f"ss-human-review-retention-{suffix}"
    token, _ = create_access_token(user_id=supervisor_id, role="SUPERVISOR")
    image_locked = Event()
    allow_retention_commit = Event()
    request_started = Event()
    request_finished = Event()
    request_result: dict[str, object] = {}

    def retention_transaction() -> None:
        with SessionLocal() as db:
            image = (
                db.query(models.ShelfImage)
                .filter(models.ShelfImage.id == image_id)
                .with_for_update()
                .one()
            )
            image_locked.set()
            if not allow_retention_commit.wait(timeout=20):
                raise TimeoutError("retention lock holder was not released")
            image.retention_status = "RESTRICTED"
            image.retention_reason = "PostgreSQL human-review concurrency smoke"
            image.retention_requested_at = models.utc_now()
            db.commit()

    def scoped_get_db():
        db = SessionLocal()
        try:
            db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": application_name},
            )
            request_started.set()
            yield db
        finally:
            db.close()

    def submit_human_review() -> None:
        app.dependency_overrides[main_module.get_db] = scoped_get_db
        try:
            with TestClient(app) as client:
                response = client.post(
                    f"/api/v1/shelf-image-detections/{detection_id}/reviews",
                    json={"decision": "REJECTED", "notes": "Retention race smoke"},
                    headers={"Authorization": f"Bearer {token}"},
                )
            request_result["status_code"] = response.status_code
            request_result["body"] = response.json()
        finally:
            app.dependency_overrides.pop(main_module.get_db, None)
            request_finished.set()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            retention_future = executor.submit(retention_transaction)
            review_future = None
            try:
                assert image_locked.wait(timeout=10), (
                    "retention transaction did not lock source image"
                )
                review_future = executor.submit(submit_human_review)
                assert request_started.wait(timeout=10), (
                    "human-review HTTP request did not start"
                )

                deadline = monotonic() + 12
                observed_blocker = False
                while monotonic() < deadline:
                    with SessionLocal() as monitor:
                        activity = monitor.execute(
                            text(
                                "SELECT wait_event_type, pg_blocking_pids(pid) "
                                "FROM pg_stat_activity WHERE application_name = :name"
                            ),
                            {"name": application_name},
                        ).first()
                    if activity is not None and activity[0] == "Lock" and activity[1]:
                        observed_blocker = True
                        break
                    if request_finished.is_set():
                        break
                    sleep(0.05)

                assert observed_blocker, (
                    "human-review request did not wait on the source-image row lock"
                )
                assert not request_finished.is_set(), (
                    "human-review request returned before retention committed"
                )
            finally:
                allow_retention_commit.set()

            retention_future.result(timeout=15)
            if review_future is not None:
                review_future.result(timeout=15)

        assert request_result.get("status_code") == 410, request_result
        with SessionLocal() as db:
            image = db.get(models.ShelfImage, image_id)
            assert image is not None and image.retention_status == "RESTRICTED"
            reviews = (
                db.query(models.DetectionSkuReview)
                .filter(models.DetectionSkuReview.detection_id == detection_id)
                .count()
            )
            assert reviews == 0, (
                "a human review was persisted after the source image was restricted"
            )
    finally:
        app.dependency_overrides.pop(main_module.get_db, None)
        main_module.settings = original_settings

    print(
        "PostgreSQL human-review retention smoke passed: the review HTTP "
        "request waited for the source-image lock, observed RESTRICTED after "
        "the competing commit, returned HTTP 410, and persisted no review."
    )


if __name__ == "__main__":
    main()
