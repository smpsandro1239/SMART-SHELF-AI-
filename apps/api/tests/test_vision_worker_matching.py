from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import models
from app.vision import DetectionResult
from app.vision_worker import resolve_sku_match


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        reviewer = models.User(
            email="reviewer@worker.test",
            full_name="Reviewer",
            password_hash="test-hash",
            role="ADMIN",
            is_active=True,
        )
        product = models.Product(sku="SKU-WORKER-1", name="Produto teste")
        session.add_all([reviewer, product])
        session.flush()
        session.info["reviewer_id"] = reviewer.id
        session.info["product_id"] = product.id
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def add_approved_exemplar(db, product_id, reviewer_id, vector, digest):
    db.add(models.ProductEmbeddingExemplar(
        product_id=product_id,
        embedding=vector,
        embedding_dimension=len(vector),
        model_version="embed-v1",
        image_sha256=digest * 64,
        licence="store-owned-test-image",
        review_status="APPROVED",
        reviewed_by_user_id=reviewer_id,
        reviewed_at=models.utc_now(),
    ))
    db.flush()


def test_worker_abstains_when_provider_does_not_return_embedding(db):
    detection = DetectionResult(
        label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
    )
    result = resolve_sku_match(db, detection)
    assert result == {"product_id": None, "status": "UNKNOWN", "similarity": None, "margin": None}


def test_worker_matches_only_approved_exemplar_of_same_embedding_version(db):
    add_approved_exemplar(
        db, db.info["product_id"], db.info["reviewer_id"], [1.0, 0.0, 0.0], "a"
    )
    detection = DetectionResult(
        label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
        embedding=[0.99, 0.01, 0.0],
        embedding_model_version="embed-v1",
    )
    result = resolve_sku_match(db, detection)
    assert result["status"] == "MATCHED"
    assert result["product_id"] == db.info["product_id"]
    assert result["similarity"] > 0.99


def test_worker_abstains_for_unapproved_or_different_version_exemplars(db):
    product_id = db.info["product_id"]
    db.add(models.ProductEmbeddingExemplar(
        product_id=product_id,
        embedding=[1.0, 0.0, 0.0],
        embedding_dimension=3,
        model_version="embed-v2",
        image_sha256="b" * 64,
        licence="store-owned-test-image",
        review_status="PENDING",
    ))
    db.flush()
    detection = DetectionResult(
        label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
        embedding=[1.0, 0.0, 0.0],
        embedding_model_version="embed-v1",
    )
    result = resolve_sku_match(db, detection)
    assert result["status"] == "UNKNOWN"
    assert result["product_id"] is None


def test_detection_rejects_embedding_without_model_version():
    with pytest.raises(ValueError):
        DetectionResult(
            label="product", confidence=0.9,
            x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
            embedding=[1.0, 0.0],
        )


def test_worker_reuses_registry_for_detections_with_same_embedding_version(db, monkeypatch):
    import app.vision_worker as worker

    product_id = db.info["product_id"]
    add_approved_exemplar(
        db, product_id, db.info["reviewer_id"], [1.0, 0.0, 0.0], "c"
    )
    calls = []
    original = worker.build_approved_product_registry

    def counted_registry(session, *, model_version, **kwargs):
        calls.append(model_version)
        return original(session, model_version=model_version, **kwargs)

    monkeypatch.setattr(worker, "build_approved_product_registry", counted_registry)
    cache = {}
    detections = [
        DetectionResult(
            label="product", confidence=0.9,
            x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
            embedding=[1.0, 0.0, 0.0],
            embedding_model_version="embed-v1",
        )
        for _ in range(3)
    ]

    results = [worker.resolve_sku_match(db, item, cache) for item in detections]

    assert all(item["status"] == "MATCHED" for item in results)
    assert calls == ["embed-v1"]



def test_worker_uses_configured_similarity_threshold(db, monkeypatch):
    import app.vision_worker as worker

    add_approved_exemplar(
        db, db.info["product_id"], db.info["reviewer_id"], [1.0, 0.0, 0.0], "d"
    )
    monkeypatch.setattr(worker.settings, "product_matching_min_similarity", 1.0)
    detection = DetectionResult(
        label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
        embedding=[0.99, 0.01, 0.0],
        embedding_model_version="embed-v1",
    )

    result = worker.resolve_sku_match(db, detection)

    assert result["status"] == "UNKNOWN"
    assert result["product_id"] is None


def test_worker_ocr_persists_assigned_and_unassigned_regions_without_stock_mutation(db, tmp_path, monkeypatch):
    from app.ocr_paddle import OCRRegion
    from app.product_text import OCRText
    from app.vision_worker import persist_ocr_evidence

    store = models.Store(code="OCR-WORKER", name="OCR Worker")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="OCR-01")
    db.add(shelf)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id, original_filename="worker.jpg",
        storage_path=str(tmp_path / "worker.jpg"), mime_type="image/jpeg",
        file_size_bytes=10, sha256="e" * 64, analysis_status="PROCESSING",
        model_version="detector-v1",
    )
    db.add(image)
    db.flush()
    detection = models.ShelfImageDetection(
        shelf_image_id=image.id, label="product", confidence=0.9,
        x_min=0.1, y_min=0.1, x_max=0.6, y_max=0.8,
        model_version="detector-v1",
    )
    db.add(detection)
    db.flush()

    class FakeOCR:
        def recognize(self, path):
            return (
                OCRRegion(OCRText("Leite Meio-Gordo 1 L", 0.94), 0.2, 0.2, 0.5, 0.3),
                OCRRegion(OCRText("PROMOÇÃO", 0.8), 0.8, 0.05, 0.95, 0.1),
            )

    persist_ocr_evidence(db, image.id, tmp_path / "worker.jpg", [detection], FakeOCR())
    db.flush()
    run = db.query(models.ShelfImageOCRRun).filter_by(shelf_image_id=image.id).one()
    evidence = db.query(models.ShelfImageOCREvidence).filter_by(run_id=run.id).order_by(models.ShelfImageOCREvidence.id).all()
    assert run.status == "COMPLETED"
    assert evidence[0].detection_id == detection.id
    assert evidence[0].association_status == "ASSIGNED"
    assert evidence[1].detection_id is None
    assert evidence[1].association_status == "UNASSIGNED"
    assert db.query(models.InventorySnapshot).count() == 0


def test_optional_ocr_failure_is_recorded_without_raising_or_mutating_inventory(db, tmp_path):
    from app.vision_worker import persist_ocr_evidence

    store = models.Store(code="OCR-FAIL", name="OCR Failure")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="OCR-FAIL-01")
    db.add(shelf)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id, original_filename="failed.jpg",
        storage_path=str(tmp_path / "failed.jpg"), mime_type="image/jpeg",
        file_size_bytes=10, sha256="f" * 64, analysis_status="COMPLETED",
        model_version="detector-v1",
    )
    db.add(image)
    db.flush()

    class BrokenOCR:
        def recognize(self, path):
            raise RuntimeError("simulated OCR runtime failure")

    persist_ocr_evidence(db, image.id, tmp_path / "failed.jpg", [], BrokenOCR())
    db.flush()
    run = db.query(models.ShelfImageOCRRun).filter_by(shelf_image_id=image.id).one()
    assert run.status == "FAILED"
    assert db.query(models.InventorySnapshot).count() == 0



@pytest.mark.parametrize("retention_status", ["RESTRICTED", "PENDING_PURGE", "PURGED"])
def test_worker_does_not_claim_non_active_pending_images(db, tmp_path, retention_status):
    import app.vision_worker as worker

    store = models.Store(code=f"NONACTIVE-WORKER-{retention_status}", name="Non-active Worker")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="RESTRICTED-01")
    db.add(shelf)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="non-active.jpg",
        storage_path=str(tmp_path / "non-active.jpg"),
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256="9" * 64,
        analysis_status="PENDING",
        retention_status=retention_status,
    )
    db.add(image)
    db.flush()

    class MustNotRun:
        def analyze(self, path):
            raise AssertionError("restricted image must not be sent to inference")

    assert worker.process_next_image(db, MustNotRun()) is None
    db.refresh(image)
    assert image.analysis_status == "PENDING"


def test_worker_stops_before_ocr_when_image_is_restricted_during_inference(db, tmp_path, monkeypatch):
    import app.vision_worker as worker
    from app.vision import DetectionResult, VisionAnalysis

    store = models.Store(code="RACE-WORKER", name="Retention Race")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="RACE-01")
    db.add(shelf)
    db.flush()
    storage_root = tmp_path / "storage"
    monkeypatch.setattr(worker.settings, "image_storage_path", str(storage_root))
    image_path = storage_root / str(store.id) / "race.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"test-image")
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="race.jpg",
        storage_path=str(image_path),
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256="a" * 64,
        analysis_status="PENDING",
        retention_status="ACTIVE",
    )
    db.add(image)
    db.commit()
    image_id = image.id

    class RestrictingVisionProvider:
        def analyze(self, path):
            # Simulate a separately committed retention request while inference runs.
            stored = db.get(models.ShelfImage, image_id)
            stored.retention_status = "RESTRICTED"
            stored.retention_reason = "Pedido de privacidade"
            db.commit()
            return VisionAnalysis(
                model_version="detector-race-v1",
                detections=[
                    DetectionResult(
                        label="product",
                        confidence=0.95,
                        x_min=0.1,
                        y_min=0.1,
                        x_max=0.8,
                        y_max=0.8,
                    )
                ],
            )

    class MustNotRunOCR:
        def recognize(self, path):
            raise AssertionError("OCR must not process an image restricted during inference")

    processed = worker.process_next_image(
        db,
        RestrictingVisionProvider(),
        ocr_provider=MustNotRunOCR(),
    )

    assert processed == image_id
    stored_image = db.get(models.ShelfImage, image_id)
    assert stored_image.retention_status == "RESTRICTED"
    assert stored_image.analysis_status == "FAILED"
    assert stored_image.analysis_error == "Image restricted during processing"
    assert db.query(models.ShelfImageDetection).filter_by(shelf_image_id=image_id).count() == 0
    assert db.query(models.ShelfImageOCRRun).filter_by(shelf_image_id=image_id).count() == 0




def test_worker_does_not_fail_image_after_losing_processing_lease(db, tmp_path, monkeypatch):
    import app.vision_worker as worker

    store = models.Store(code="LEASE-LOSS", name="Lease Loss")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="LEASE-01")
    db.add(shelf)
    db.flush()

    storage_root = tmp_path / "storage"
    monkeypatch.setattr(worker.settings, "image_storage_path", str(storage_root))
    image_path = storage_root / str(store.id) / "lease.jpg"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"test-image")
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="lease.jpg",
        storage_path=str(image_path),
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256="f" * 64,
        analysis_status="PENDING",
        retention_status="ACTIVE",
    )
    db.add(image)
    db.commit()
    image_id = image.id
    replacement_lease = models.utc_now() + timedelta(seconds=30)

    class LeaseTakingOverProvider:
        def analyze(self, path):
            stored = db.get(models.ShelfImage, image_id)
            stored.analysis_status = "PROCESSING"
            stored.analysis_started_at = replacement_lease
            stored.analysis_error = None
            db.commit()
            raise RuntimeError("old worker failed after lease takeover")

    assert worker.process_next_image(db, LeaseTakingOverProvider()) == image_id

    stored_image = db.get(models.ShelfImage, image_id)
    assert stored_image.analysis_status == "PROCESSING"
    assert worker._same_claim_timestamp(stored_image.analysis_started_at, replacement_lease)
    assert stored_image.analysis_error is None
    assert stored_image.analysis_completed_at is None


def test_worker_rejects_image_path_outside_owning_store_directory(db, tmp_path, monkeypatch):
    import app.vision_worker as worker

    store = models.Store(code="PATH-GUARD", name="Path Guard")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="PATH-01")
    db.add(shelf)
    db.flush()
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    outside_path = tmp_path / "outside.jpg"
    outside_path.write_bytes(b"not-an-image")
    monkeypatch.setattr(worker.settings, "image_storage_path", str(storage_root))
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="outside.jpg",
        storage_path=str(outside_path),
        mime_type="image/jpeg",
        file_size_bytes=13,
        sha256="b" * 64,
        analysis_status="PENDING",
        retention_status="ACTIVE",
    )
    db.add(image)
    db.commit()
    image_id = image.id

    class MustNotRun:
        def analyze(self, path):
            raise AssertionError("worker must never read a file outside the owning store directory")

    assert worker.process_next_image(db, MustNotRun()) == image_id
    stored_image = db.get(models.ShelfImage, image_id)
    assert stored_image.analysis_status == "FAILED"
    assert stored_image.analysis_error == "FileNotFoundError: processing failed"


def test_worker_rejects_symlinked_image_file(db, tmp_path, monkeypatch):
    import app.vision_worker as worker

    store = models.Store(code="SYMLINK-GUARD", name="Symlink Guard")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="SYMLINK-01")
    db.add(shelf)
    db.flush()
    storage_root = tmp_path / "storage"
    store_dir = storage_root / str(store.id)
    store_dir.mkdir(parents=True)
    outside_path = tmp_path / "outside.jpg"
    outside_path.write_bytes(b"not-an-image")
    linked_path = store_dir / "linked.jpg"
    try:
        linked_path.symlink_to(outside_path)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"Symlinks are unavailable in this test environment: {exc}")
    monkeypatch.setattr(worker.settings, "image_storage_path", str(storage_root))
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="linked.jpg",
        storage_path=str(linked_path),
        mime_type="image/jpeg",
        file_size_bytes=13,
        sha256="c" * 64,
        analysis_status="PENDING",
        retention_status="ACTIVE",
    )
    db.add(image)
    db.commit()
    image_id = image.id

    class MustNotRun:
        def analyze(self, path):
            raise AssertionError("worker must not follow a symlinked image file")

    assert worker.process_next_image(db, MustNotRun()) == image_id
    stored_image = db.get(models.ShelfImage, image_id)
    assert stored_image.analysis_status == "FAILED"
    assert stored_image.analysis_error == "FileNotFoundError: processing failed"


@pytest.mark.parametrize("symlink_component", ["store_directory", "nested_directory"])
def test_worker_rejects_symlinked_store_or_nested_directory(
    db, tmp_path, monkeypatch, symlink_component
):
    import app.vision_worker as worker

    store = models.Store(
        code=f"SYMLINK-DIR-{symlink_component.upper()}",
        name="Symlink Directory Guard",
    )
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="SYMLINK-DIR-01")
    db.add(shelf)
    db.flush()

    storage_root = tmp_path / "storage"
    store_root = storage_root / str(store.id)
    outside_root = tmp_path / "outside"
    outside_root.mkdir()
    linked_file = outside_root / "linked.jpg"
    linked_file.write_bytes(b"not-an-image")

    if symlink_component == "store_directory":
        try:
            store_root.symlink_to(outside_root, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"Directory symlinks are unavailable: {exc}")
        stored_path = store_root / linked_file.name
    else:
        store_root.mkdir(parents=True)
        nested_link = store_root / "nested"
        try:
            nested_link.symlink_to(outside_root, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            pytest.skip(f"Directory symlinks are unavailable: {exc}")
        stored_path = nested_link / linked_file.name

    monkeypatch.setattr(worker.settings, "image_storage_path", str(storage_root))
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="linked.jpg",
        storage_path=str(stored_path),
        mime_type="image/jpeg",
        file_size_bytes=13,
        sha256="d" * 64,
        analysis_status="PENDING",
        retention_status="ACTIVE",
    )
    db.add(image)
    db.commit()
    image_id = image.id

    class MustNotRun:
        def analyze(self, path):
            raise AssertionError(
                "worker must reject symlinked store and nested directories"
            )

    assert worker.process_next_image(db, MustNotRun()) == image_id
    stored_image = db.get(models.ShelfImage, image_id)
    assert stored_image.analysis_status == "FAILED"
    assert stored_image.analysis_error == "FileNotFoundError: processing failed"



def test_worker_excludes_exemplar_when_its_source_image_is_restricted(db):
    store = models.Store(code="EMBED-RETENTION", name="Embedding retention")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="EMBED-01")
    db.add(shelf)
    db.flush()
    source_image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="reference.jpg",
        storage_path="/tmp/reference.jpg",
        mime_type="image/jpeg",
        file_size_bytes=10,
        sha256="e" * 64,
        retention_status="ACTIVE",
    )
    db.add(source_image)
    db.flush()
    exemplar = models.ProductEmbeddingExemplar(
        product_id=db.info["product_id"],
        shelf_image_id=source_image.id,
        embedding=[1.0, 0.0, 0.0],
        embedding_dimension=3,
        model_version="embed-v1",
        image_sha256="e" * 64,
        licence="store-owned-test-image",
        review_status="APPROVED",
        reviewed_by_user_id=db.info["reviewer_id"],
        reviewed_at=models.utc_now(),
    )
    db.add(exemplar)
    db.flush()

    detection = DetectionResult(
        label="product",
        confidence=0.9,
        x_min=0.1,
        y_min=0.1,
        x_max=0.8,
        y_max=0.8,
        embedding=[1.0, 0.0, 0.0],
        embedding_model_version="embed-v1",
    )
    active_result = resolve_sku_match(db, detection, {})
    assert active_result["status"] == "MATCHED"
    assert active_result["product_id"] == db.info["product_id"]

    source_image.retention_status = "RESTRICTED"
    db.flush()
    restricted_result = resolve_sku_match(db, detection, {})

    assert restricted_result["status"] == "UNKNOWN"
    assert restricted_result["product_id"] is None
