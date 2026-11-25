"""Prove the shelf-image review queue serializes with PostgreSQL retention.

A queue request selects its page, then locks the source images before returning
derived evidence. This smoke test holds the source-image row lock in one
transaction, starts the real HTTP endpoint in another session, observes the
request waiting in pg_stat_activity, and restricts the image before releasing
the lock. The endpoint must then re-check eligibility and return an empty page.
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


def _bearer(user_id: int) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id, role="SUPERVISOR")
    return {"Authorization": f"Bearer {token}"}


def create_fixture(suffix: str) -> tuple[int, int, int]:
    with SessionLocal() as db:
        store = models.Store(
            code=f"PG-REVIEW-QUEUE-{suffix}",
            name="PostgreSQL review queue retention smoke",
        )
        db.add(store)
        db.flush()
        supervisor = models.User(
            email=f"pg-review-queue-supervisor-{suffix}@example.test",
            full_name="Review queue smoke supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store.id,
            is_active=True,
        )
        db.add(supervisor)
        db.flush()

        zone = models.Zone(store_id=store.id, name="Review queue smoke zone")
        db.add(zone)
        db.flush()

        shelf = models.Shelf(zone_id=zone.id, code=f"PG-QUEUE-{suffix}")
        db.add(shelf)
        db.flush()

        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="review-queue-smoke.jpg",
            storage_path=f"/tmp/review-queue-smoke-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256=("a" * 64),
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
            model_version="pg-review-queue-v1",
        )
        db.add(detection)
        db.flush()

        ocr_run = models.ShelfImageOCRRun(
            shelf_image_id=image.id,
            provider="postgres-smoke",
            model_version="pg-review-queue-ocr-v1",
            status="COMPLETED",
        )
        db.add(ocr_run)
        db.flush()

        db.add(models.ShelfImageFusedEvidence(
            ocr_run_id=ocr_run.id,
            detection_id=detection.id,
            status="CONFLICT",
            suggested_product_id=None,
            visual_product_id=None,
            text_product_id=None,
            visual_status="MATCHED",
            text_status="SUGGESTED",
            visual_similarity=0.91,
            text_score=0.92,
            ocr_confidence=0.96,
            visual_model_version="pg-review-queue-v1",
            ocr_provider="postgres-smoke",
            ocr_model_version="pg-review-queue-ocr-v1",
            reason="PostgreSQL review queue retention smoke",
        ))
        db.commit()
        return image.id, detection.id, supervisor.id


def main() -> None:
    suffix = uuid4().hex[:10]
    image_id, _detection_id, supervisor_id = create_fixture(suffix)
    application_name = f"ss-review-queue-{suffix}"
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
                raise TimeoutError("review queue lock holder was not released")
            image.retention_status = "RESTRICTED"
            image.retention_reason = "PostgreSQL review queue concurrency smoke"
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

    def request_review_queue() -> None:
        app.dependency_overrides[main_module.get_db] = scoped_get_db
        try:
            with TestClient(app) as client:
                response = client.get(
                    "/api/v1/shelf-image-review-queue",
                    headers=_bearer(supervisor_id),
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
            queue_future = None
            try:
                assert image_locked.wait(timeout=10), (
                    "retention transaction did not lock source image"
                )
                queue_future = executor.submit(request_review_queue)
                assert request_started.wait(timeout=10), (
                    "review queue request did not start"
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
                    "review queue request did not wait on the source-image row lock"
                )
                assert not request_finished.is_set(), (
                    "review queue returned before the retention transaction released its lock"
                )
            finally:
                allow_retention_commit.set()

            retention_future.result(timeout=15)
            if queue_future is not None:
                queue_future.result(timeout=15)

        assert request_result.get("status_code") == 200, request_result
        assert request_result.get("body") == [], (
            "review queue exposed derived evidence after the source image was restricted: "
            f"{request_result}"
        )

        with SessionLocal() as db:
            image = db.get(models.ShelfImage, image_id)
            assert image is not None
            assert image.retention_status == "RESTRICTED"

    finally:
        app.dependency_overrides.pop(main_module.get_db, None)
        main_module.settings = original_settings

    print(
        "PostgreSQL review-queue retention smoke passed: the store-scoped HTTP "
        "request waited on the source-image lock, refreshed eligibility after "
        "retention committed, and returned no derived evidence for the restricted image."
    )


if __name__ == "__main__":
    main()
