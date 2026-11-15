"""Prove PostgreSQL row-lock serialization between SKU matching and image retention.

The worker locks the target image and approved exemplar source images in one
ascending-ID pass. The retention endpoint uses SELECT FOR UPDATE on the same
shelf_images row. This smoke test uses two independent PostgreSQL sessions and
checks pg_stat_activity to prove the retention transaction is actually blocked
by the matching transaction before allowing matching to commit.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app import main as main_module
from app import models
from app.database import SessionLocal
from app.product_embedding_service import (
    build_approved_product_registry,
    lock_matching_source_images,
)


def _create_fixture(suffix: str) -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        store = models.Store(
            code=f"PG-EMBED-LOCK-{suffix}",
            name="PostgreSQL embedding retention smoke",
        )
        product = models.Product(
            sku=f"PG-EMBED-SKU-{suffix}",
            name="PostgreSQL embedding reference",
        )
        reviewer = models.User(
            email=f"pg-embed-reviewer-{suffix}@example.test",
            full_name="PostgreSQL embedding reviewer",
            password_hash="smoke-test-only",
            role="ADMIN",
            is_active=True,
        )
        db.add_all([store, product, reviewer])
        db.flush()

        zone = models.Zone(store_id=store.id, name="Smoke zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PG-EMBED-{suffix}")
        db.add(shelf)
        db.flush()

        source_image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="approved-reference.jpg",
            storage_path=f"/tmp/pg-embed-source-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="a" * 64,
            retention_status="ACTIVE",
        )
        target_image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="worker-target.jpg",
            storage_path=f"/tmp/pg-embed-target-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="b" * 64,
            retention_status="ACTIVE",
        )
        db.add_all([source_image, target_image])
        db.flush()

        db.add(models.ProductEmbeddingExemplar(
            product_id=product.id,
            shelf_image_id=source_image.id,
            embedding=[1.0, 0.0, 0.0],
            embedding_dimension=3,
            model_version="pg-embedding-lock-v1",
            image_sha256="a" * 64,
            licence="store-owned-smoke-reference",
            review_status="APPROVED",
            reviewed_by_user_id=reviewer.id,
            reviewed_at=models.utc_now(),
        ))
        target_detection = models.ShelfImageDetection(
            shelf_image_id=target_image.id,
            label="product",
            confidence=0.95,
            x_min=0.1,
            y_min=0.1,
            x_max=0.8,
            y_max=0.9,
            model_version="pg-vision-lineage-v1",
        )
        target_ocr_run = models.ShelfImageOCRRun(
            shelf_image_id=target_image.id,
            provider="smoke",
            model_version="pg-ocr-lineage-v1",
            status="COMPLETED",
        )
        db.add_all([target_detection, target_ocr_run])
        db.flush()
        target_ocr_evidence = models.ShelfImageOCREvidence(
            run_id=target_ocr_run.id,
            detection_id=target_detection.id,
            text="SKU-123",
            normalized_text="SKU123",
            confidence=0.99,
            x_min=0.1,
            y_min=0.1,
            x_max=0.8,
            y_max=0.2,
            association_status="ASSIGNED",
        )
        db.add(target_ocr_evidence)
        db.add(models.DetectionSkuReview(
            detection_id=target_detection.id,
            previous_product_id=None,
            selected_product_id=product.id,
            decision="CONFIRMED",
            reviewer_user_id=reviewer.id,
            notes="PostgreSQL lineage smoke",
        ))
        db.add(models.ShelfImageOCRMatch(
            run_id=target_ocr_run.id,
            detection_id=target_detection.id,
            suggested_product_id=product.id,
            observed_text="SKU-123",
            ocr_confidence=0.99,
            status="SUGGESTED",
            top_score=0.99,
            margin=0.2,
            candidates=[{"product_id": product.id, "score": 0.99}],
        ))
        db.add(models.ShelfImageFusedEvidence(
            ocr_run_id=target_ocr_run.id,
            detection_id=target_detection.id,
            status="CONSENSUS",
            suggested_product_id=product.id,
            visual_product_id=product.id,
            text_product_id=product.id,
            visual_status="MATCHED",
            text_status="MATCHED",
            visual_similarity=0.99,
            text_score=0.99,
            ocr_confidence=0.99,
            visual_model_version="pg-vision-lineage-v1",
            ocr_provider="smoke",
            ocr_model_version="pg-ocr-lineage-v1",
            reason="PostgreSQL lineage smoke",
        ))
        db.commit()
        return source_image.id, target_image.id, product.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    suffix = uuid4().hex[:8]
    source_image_id, target_image_id, _product_id = _create_fixture(suffix)
    application_name = f"ss-retention-{suffix}"
    matching_locked = Event()
    allow_matching_commit = Event()
    retention_started = Event()
    retention_finished = Event()

    def matching_transaction() -> None:
        with SessionLocal() as db:
            lock_matching_source_images(
                db,
                target_image_id=target_image_id,
                model_versions={"pg-embedding-lock-v1"},
            )
            matching_locked.set()
            if not allow_matching_commit.wait(timeout=15):
                raise TimeoutError("matching transaction was not released")
            db.commit()

    def retention_transaction() -> None:
        with SessionLocal() as db:
            db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": application_name},
            )
            retention_started.set()
            image = (
                db.query(models.ShelfImage)
                .filter(models.ShelfImage.id == source_image_id)
                .with_for_update()
                .one()
            )
            image.retention_status = "RESTRICTED"
            image.retention_reason = "PostgreSQL lock serialization smoke"
            image.retention_requested_at = models.utc_now()
            db.commit()
            retention_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        matching_future = executor.submit(matching_transaction)
        assert matching_locked.wait(timeout=10), "matching did not acquire source-image locks"
        retention_future = executor.submit(retention_transaction)
        assert retention_started.wait(timeout=10), "retention transaction did not start"

        deadline = monotonic() + 10
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
            if retention_finished.is_set():
                break
            sleep(0.05)

        try:
            assert observed_blocker, (
                "retention did not appear as a PostgreSQL lock waiter blocked "
                "by the matching transaction"
            )
            assert not retention_finished.is_set(), (
                "retention completed before matching released its source-image lock"
            )
        finally:
            allow_matching_commit.set()

        matching_future.result(timeout=10)
        retention_future.result(timeout=10)

    assert retention_finished.is_set(), "retention did not complete after matching commit"

    with SessionLocal() as db:
        source_image = db.get(models.ShelfImage, source_image_id)
        assert source_image is not None
        assert source_image.retention_status == "RESTRICTED"
        registry = build_approved_product_registry(
            db,
            model_version="pg-embedding-lock-v1",
        )
        result = registry.match([1.0, 0.0, 0.0])
        assert result.status == "UNKNOWN", result

    # Manual OCR matching must serialize with retention just like the
    # background worker. The API route locks and refreshes the source image;
    # after retention commits, the waiting request must observe RESTRICTED.
    with SessionLocal() as db:
        reviewer_id = db.query(models.User.id).filter(
            models.User.email == f"pg-embed-reviewer-{suffix}@example.test"
        ).scalar()
        before_matches = db.query(models.ShelfImageOCRMatch).join(
            models.ShelfImageOCRRun,
            models.ShelfImageOCRMatch.run_id == models.ShelfImageOCRRun.id,
        ).filter(models.ShelfImageOCRRun.shelf_image_id == target_image_id).count()

    ocr_application_name = f"ss-ocr-retention-{suffix}"
    image_locked = Event()
    allow_restriction_commit = Event()
    ocr_request_started = Event()
    ocr_request_finished = Event()
    ocr_request_result: dict[str, int] = {}

    def image_lock_transaction() -> None:
        with SessionLocal() as db:
            image = (
                db.query(models.ShelfImage)
                .filter(models.ShelfImage.id == target_image_id)
                .with_for_update()
                .one()
            )
            image_locked.set()
            if not allow_restriction_commit.wait(timeout=15):
                raise TimeoutError("image lock transaction was not released")
            image.retention_status = "RESTRICTED"
            image.retention_reason = "PostgreSQL OCR retention serialization smoke"
            image.retention_requested_at = models.utc_now()
            db.commit()

    def ocr_matching_request() -> None:
        with SessionLocal() as db:
            db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": ocr_application_name},
            )
            ocr_request_started.set()
            request = SimpleNamespace(state=SimpleNamespace(user_id=reviewer_id))
            try:
                main_module.match_shelf_image_ocr_to_catalogue(
                    target_image_id,
                    request,
                    db,
                )
            except HTTPException as exc:
                ocr_request_result["status_code"] = exc.status_code
            else:
                ocr_request_result["status_code"] = 200
            finally:
                ocr_request_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        lock_future = executor.submit(image_lock_transaction)
        assert image_locked.wait(timeout=10), "retention transaction did not lock OCR source image"
        ocr_future = executor.submit(ocr_matching_request)
        assert ocr_request_started.wait(timeout=10), "OCR matching request did not start"

        deadline = monotonic() + 10
        observed_ocr_blocker = False
        while monotonic() < deadline:
            with SessionLocal() as monitor:
                activity = monitor.execute(
                    text(
                        "SELECT wait_event_type, pg_blocking_pids(pid) "
                        "FROM pg_stat_activity WHERE application_name = :name"
                    ),
                    {"name": ocr_application_name},
                ).first()
            if activity is not None and activity[0] == "Lock" and activity[1]:
                observed_ocr_blocker = True
                break
            if ocr_request_finished.is_set():
                break
            sleep(0.05)

        try:
            assert observed_ocr_blocker, (
                "manual OCR matching did not wait for the source-image retention lock"
            )
            assert not ocr_request_finished.is_set(), (
                "manual OCR matching completed before the retention decision committed"
            )
        finally:
            allow_restriction_commit.set()

        lock_future.result(timeout=10)
        ocr_future.result(timeout=10)

    assert ocr_request_result.get("status_code") == 410, ocr_request_result
    with SessionLocal() as db:
        image = db.get(models.ShelfImage, target_image_id)
        assert image is not None and image.retention_status == "RESTRICTED"
        after_matches = db.query(models.ShelfImageOCRMatch).join(
            models.ShelfImageOCRRun,
            models.ShelfImageOCRMatch.run_id == models.ShelfImageOCRRun.id,
        ).filter(models.ShelfImageOCRRun.shelf_image_id == target_image_id).count()
        assert after_matches == before_matches

    # A source-image deletion must not silently turn its derived exemplar into
    # an unlinked external reference (the FK's legacy ON DELETE SET NULL path).
    with SessionLocal() as db:
        try:
            db.query(models.ShelfImage).filter(
                models.ShelfImage.id == source_image_id
            ).delete(synchronize_session=False)
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError(
                "source image deletion detached a derived embedding exemplar"
            )

        exemplar = (
            db.query(models.ProductEmbeddingExemplar)
            .filter(models.ProductEmbeddingExemplar.image_sha256 == "a" * 64)
            .one()
        )
        assert exemplar.shelf_image_id == source_image_id

    # Deleting an image with detections/OCR must not cascade away the
    # human-review and OCR evidence lineage.
    with SessionLocal() as db:
        try:
            db.query(models.ShelfImage).filter(
                models.ShelfImage.id == target_image_id
            ).delete(synchronize_session=False)
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError(
                "source image deletion cascaded into visual/OCR evidence"
            )

        assert db.query(models.ShelfImage).filter(
            models.ShelfImage.id == target_image_id
        ).one_or_none() is not None
        assert db.query(models.ShelfImageDetection).filter(
            models.ShelfImageDetection.shelf_image_id == target_image_id
        ).count() == 1
        assert db.query(models.ShelfImageOCRRun).filter(
            models.ShelfImageOCRRun.shelf_image_id == target_image_id
        ).count() == 1
        assert db.query(models.ShelfImageOCREvidence).filter(
            models.ShelfImageOCREvidence.text == "SKU-123"
        ).count() == 1
        assert db.query(models.DetectionSkuReview).filter(
            models.DetectionSkuReview.notes == "PostgreSQL lineage smoke"
        ).count() == 1
        assert db.query(models.ShelfImageOCRMatch).filter(
            models.ShelfImageOCRMatch.observed_text == "SKU-123"
        ).count() == 1
        assert db.query(models.ShelfImageFusedEvidence).filter(
            models.ShelfImageFusedEvidence.reason == "PostgreSQL lineage smoke"
        ).count() == 1

    # Direct deletion of a detection must not cascade away its human review,
    # OCR association, matching or fused evidence.
    with SessionLocal() as db:
        detection = db.query(models.ShelfImageDetection).filter(
            models.ShelfImageDetection.shelf_image_id == target_image_id
        ).one()
        detection_id = detection.id
        try:
            db.delete(detection)
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError(
                "detection deletion cascaded into human review or derived evidence"
            )
        assert db.query(models.DetectionSkuReview).filter(
            models.DetectionSkuReview.detection_id == detection_id
        ).count() == 1
        assert db.query(models.ShelfImageOCREvidence).filter(
            models.ShelfImageOCREvidence.detection_id == detection_id
        ).count() == 1
        assert db.query(models.ShelfImageOCRMatch).filter(
            models.ShelfImageOCRMatch.detection_id == detection_id
        ).count() == 1
        assert db.query(models.ShelfImageFusedEvidence).filter(
            models.ShelfImageFusedEvidence.detection_id == detection_id
        ).count() == 1

    # Direct deletion of an OCR run must preserve its text, matches and fusion.
    with SessionLocal() as db:
        ocr_run = db.query(models.ShelfImageOCRRun).filter(
            models.ShelfImageOCRRun.shelf_image_id == target_image_id
        ).one()
        ocr_run_id = ocr_run.id
        try:
            db.delete(ocr_run)
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError(
                "OCR run deletion cascaded into OCR or fused evidence"
            )
        assert db.query(models.ShelfImageOCREvidence).filter(
            models.ShelfImageOCREvidence.run_id == ocr_run_id
        ).count() == 1
        assert db.query(models.ShelfImageOCRMatch).filter(
            models.ShelfImageOCRMatch.run_id == ocr_run_id
        ).count() == 1
        assert db.query(models.ShelfImageFusedEvidence).filter(
            models.ShelfImageFusedEvidence.ocr_run_id == ocr_run_id
        ).count() == 1

    # Human decisions and every OCR-derived artifact are immutable at
    # database level: direct UPDATE and DELETE must both be rejected.
    immutable_records = (
        (
            models.DetectionSkuReview,
            "notes",
            "PostgreSQL lineage smoke",
            "tampered human review",
            "human review",
        ),
        (
            models.ShelfImageOCRRun,
            "provider",
            "smoke",
            "tampered provider",
            "OCR run",
        ),
        (
            models.ShelfImageOCREvidence,
            "text",
            "SKU-123",
            "TAMPERED",
            "OCR text evidence",
        ),
        (
            models.ShelfImageOCRMatch,
            "observed_text",
            "SKU-123",
            "TAMPERED",
            "OCR catalogue match",
        ),
        (
            models.ShelfImageFusedEvidence,
            "reason",
            "PostgreSQL lineage smoke",
            "tampered fusion",
            "fused evidence",
        ),
    )
    for model, field, original_value, tampered_value, label in immutable_records:
        with SessionLocal() as db:
            record = db.query(model).filter(
                getattr(model, field) == original_value
            ).one()
            record_id = record.id
            try:
                db.query(model).filter(model.id == record_id).update(
                    {field: tampered_value},
                    synchronize_session=False,
                )
                db.commit()
            except IntegrityError:
                db.rollback()
            else:
                raise AssertionError(f"{label} UPDATE was not blocked")
            assert db.query(model).filter(
                model.id == record_id,
                getattr(model, field) == original_value,
            ).count() == 1

        with SessionLocal() as db:
            try:
                db.query(model).filter(model.id == record_id).delete(
                    synchronize_session=False
                )
                db.commit()
            except IntegrityError:
                db.rollback()
            else:
                raise AssertionError(f"{label} DELETE was not blocked")
            assert db.query(model).filter(model.id == record_id).count() == 1

    print(
        "PostgreSQL embedding-retention concurrency smoke passed: "
        "retention was observed waiting on the matching row lock, "
        "completed after matching committed, and the restricted exemplar "
        "was excluded from the next registry, and direct source deletion "
        "was blocked to preserve embedding, detection, human-review, OCR, "
        "matching and fused-evidence lineage; direct UPDATE and DELETE were "
        "rejected for human reviews, OCR runs, OCR regions, matches and fusions."
    )


if __name__ == "__main__":
    main()
