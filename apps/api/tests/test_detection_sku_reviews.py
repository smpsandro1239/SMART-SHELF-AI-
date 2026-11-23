import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models
from app.main import app
import app.main as main_module

TEST_ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSession = sessionmaker(bind=TEST_ENGINE, autoflush=False, autocommit=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_database():
    previous_override = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous_override is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous_override
    Base.metadata.drop_all(bind=TEST_ENGINE)


def create_detection(*, proposed_product_id=None, second_product=False):
    db = TestingSession()
    store = models.Store(code="REVIEW-01", name="Loja revisão")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zona")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="S-01")
    db.add(shelf)
    db.flush()
    first = models.Product(sku="SKU-REVIEW-1", name="Produto proposto", is_active=True)
    db.add(first)
    db.flush()
    second = None
    if second_product:
        second = models.Product(sku="SKU-REVIEW-2", name="Produto correto", is_active=True)
        db.add(second)
        db.flush()
    db.add(models.ShelfProduct(shelf_id=shelf.id, product_id=first.id, target_quantity=5))
    if second is not None:
        db.add(models.ShelfProduct(shelf_id=shelf.id, product_id=second.id, target_quantity=5))
    image = models.ShelfImage(
        shelf_id=shelf.id,
        original_filename="shelf.jpg",
        storage_path="/tmp/review-shelf.jpg",
        mime_type="image/jpeg",
        file_size_bytes=100,
        sha256="d" * 64,
        analysis_status="COMPLETED",
        model_version="detector-v1",
    )
    db.add(image)
    db.flush()
    detection = models.ShelfImageDetection(
        shelf_image_id=image.id,
        product_id=proposed_product_id if proposed_product_id is not None else first.id,
        label="product",
        confidence=0.95,
        x_min=0.1,
        y_min=0.1,
        x_max=0.8,
        y_max=0.8,
        model_version="detector-v1",
        sku_match_status="MATCHED",
    )
    db.add(detection)
    db.commit()
    result = {
        "detection_id": detection.id,
        "proposed_product_id": first.id,
        "correct_product_id": second.id if second is not None else None,
        "image_id": image.id,
        "store_id": store.id,
    }
    db.close()
    return result


def test_confirmed_detection_is_recorded_without_overwriting_model_result():
    data = create_detection()
    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CONFIRMED", "notes": "SKU confirmado na prateleira"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["decision"] == "CONFIRMED"
        assert body["previous_product_id"] == data["proposed_product_id"]
        assert body["selected_product_id"] == data["proposed_product_id"]

        db = TestingSession()
        detection = db.get(models.ShelfImageDetection, data["detection_id"])
        assert detection.product_id == data["proposed_product_id"]
        db.close()


def test_correction_and_rejection_are_appended_to_review_history():
    data = create_detection(second_product=True)
    with TestClient(app) as client:
        corrected = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CORRECTED", "selected_product_id": data["correct_product_id"]},
        )
        rejected = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "REJECTED"},
        )
        history = client.get(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews"
        )

        assert corrected.status_code == 201
        assert corrected.json()["previous_product_id"] == data["proposed_product_id"]
        assert corrected.json()["selected_product_id"] == data["correct_product_id"]
        assert rejected.status_code == 201
        assert rejected.json()["selected_product_id"] is None
        assert [item["decision"] for item in history.json()] == ["CORRECTED", "REJECTED"]


def test_correction_requires_active_product_assigned_to_same_shelf():
    data = create_detection()
    db = TestingSession()
    other = models.Product(sku="SKU-OTHER", name="Produto não atribuído", is_active=True)
    db.add(other)
    db.commit()
    other_id = other.id
    db.close()

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CORRECTED", "selected_product_id": other_id},
        )
        assert response.status_code == 422



def test_human_sku_review_cannot_confirm_or_correct_to_inactive_product():
    data = create_detection(second_product=True)
    with TestingSession() as db:
        inactive = db.get(models.Product, data["proposed_product_id"])
        inactive.is_active = False
        db.commit()

    with TestClient(app) as client:
        confirmed = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CONFIRMED"},
        )
        corrected = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={
                "decision": "CORRECTED",
                "selected_product_id": data["proposed_product_id"],
            },
        )

        assert confirmed.status_code == 422
        assert corrected.status_code == 422

    with TestingSession() as db:
        assert db.query(models.DetectionSkuReview).filter(
            models.DetectionSkuReview.detection_id == data["detection_id"]
        ).count() == 0

def test_detection_review_reloads_detection_after_source_image_lock(monkeypatch):
    data = create_detection()
    original_scope_lookup = main_module._shelf_image_store_id

    def remove_detection_after_scope_lookup(db, image_id):
        store_id = original_scope_lookup(db, image_id)
        db.query(models.ShelfImageDetection).filter(
            models.ShelfImageDetection.id == data["detection_id"]
        ).delete(synchronize_session=False)
        db.commit()
        return store_id

    monkeypatch.setattr(
        main_module,
        "_shelf_image_store_id",
        remove_detection_after_scope_lookup,
    )

    with TestClient(app) as client:
        response = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CONFIRMED", "notes": "Confirmação concorrente"},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "Detection changed during review; refresh the image and retry"
    )

    with TestingSession() as db:
        assert db.query(models.DetectionSkuReview).filter(
            models.DetectionSkuReview.detection_id == data["detection_id"]
        ).count() == 0



def test_detection_review_history_supports_stable_offset_pagination():
    data = create_detection(second_product=True)
    with TestClient(app) as client:
        first = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CONFIRMED", "notes": "First review"},
        )
        second = client.post(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
            json={"decision": "CORRECTED", "selected_product_id": data["correct_product_id"]},
        )
        page_one = client.get(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews?limit=1&offset=0"
        )
        page_two = client.get(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews?limit=1&offset=1"
        )
        clamped = client.get(
            f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews?limit=0&offset=-5"
        )

    assert first.status_code == 201
    assert second.status_code == 201
    assert [item["decision"] for item in page_one.json()] == ["CONFIRMED"]
    assert [item["decision"] for item in page_two.json()] == ["CORRECTED"]
    assert [item["decision"] for item in clamped.json()] == ["CONFIRMED"]


def test_detection_review_and_history_enforce_source_image_store_scope(monkeypatch):
    data = create_detection()
    with TestingSession() as db:
        foreign_store = models.Store(code="REVIEW-FOREIGN", name="Loja estrangeira")
        db.add(foreign_store)
        db.flush()
        foreign_zone = models.Zone(store_id=foreign_store.id, name="Zona estrangeira")
        db.add(foreign_zone)
        db.flush()
        foreign_shelf = models.Shelf(zone_id=foreign_zone.id, code="S-FOREIGN")
        db.add(foreign_shelf)
        db.flush()
        foreign_image = models.ShelfImage(
            shelf_id=foreign_shelf.id,
            original_filename="foreign.jpg",
            storage_path="/tmp/foreign-review-shelf.jpg",
            mime_type="image/jpeg",
            file_size_bytes=100,
            sha256="e" * 64,
            analysis_status="COMPLETED",
            model_version="detector-v1",
        )
        actor = models.User(
            email="review-scope-supervisor@example.test",
            full_name="Supervisor da loja A",
            password_hash="test-only-not-used",
            role="SUPERVISOR",
            store_id=data["store_id"],
            is_active=True,
        )
        db.add_all([foreign_image, actor])
        db.flush()
        foreign_detection = models.ShelfImageDetection(
            shelf_image_id=foreign_image.id,
            product_id=data["proposed_product_id"],
            label="product",
            confidence=0.90,
            x_min=0.1,
            y_min=0.1,
            x_max=0.8,
            y_max=0.8,
            model_version="detector-v1",
            sku_match_status="MATCHED",
        )
        db.add(foreign_detection)
        db.commit()
        foreign_detection_id = foreign_detection.id
        actor_id = actor.id

    with TestingSession() as db:
        actor = db.get(models.User, actor_id)
        monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

        with TestClient(app) as client:
            foreign_review = client.post(
                f"/api/v1/shelf-image-detections/{foreign_detection_id}/reviews",
                json={"decision": "CONFIRMED"},
            )
            missing_review = client.post(
                "/api/v1/shelf-image-detections/2147483000/reviews",
                json={"decision": "CONFIRMED"},
            )
            foreign_history = client.get(
                f"/api/v1/shelf-image-detections/{foreign_detection_id}/reviews"
            )
            missing_history = client.get(
                "/api/v1/shelf-image-detections/2147483000/reviews"
            )
            foreign_observation = client.post(
                f"/api/v1/shelf-image-detections/{foreign_detection_id}/observation",
                json={"product_id": data["proposed_product_id"], "confirmed_status": "EMPTY"},
            )
            missing_observation = client.post(
                "/api/v1/shelf-image-detections/2147483000/observation",
                json={"product_id": data["proposed_product_id"], "confirmed_status": "EMPTY"},
            )
            own_review = client.post(
                f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews",
                json={"decision": "CONFIRMED"},
            )
            own_history = client.get(
                f"/api/v1/shelf-image-detections/{data['detection_id']}/reviews"
            )

    assert foreign_review.status_code == missing_review.status_code == 404
    assert foreign_review.json() == missing_review.json()
    assert foreign_history.status_code == missing_history.status_code == 404
    assert foreign_history.json() == missing_history.json()
    assert foreign_observation.status_code == missing_observation.status_code == 404
    assert foreign_observation.json() == missing_observation.json()
    assert own_review.status_code == 201
    assert own_history.status_code == 200
    with TestingSession() as db:
        assert db.query(models.DetectionSkuReview).filter(
            models.DetectionSkuReview.detection_id == foreign_detection_id
        ).count() == 0
        assert db.query(models.DetectionSkuReview).filter(
            models.DetectionSkuReview.detection_id == data["detection_id"]
        ).count() == 1



def test_shelf_image_upload_hides_foreign_and_missing_shelf_ids(monkeypatch):
    data = create_detection()
    with TestingSession() as db:
        foreign_store = models.Store(
            code="UPLOAD-FOREIGN",
            name="Loja estrangeira para upload",
        )
        db.add(foreign_store)
        db.flush()
        foreign_zone = models.Zone(
            store_id=foreign_store.id,
            name="Zona estrangeira",
        )
        db.add(foreign_zone)
        db.flush()
        foreign_shelf = models.Shelf(
            zone_id=foreign_zone.id,
            code="UPLOAD-FOREIGN-SHELF",
        )
        actor = models.User(
            email="upload-scope-supervisor@example.test",
            full_name="Supervisor upload",
            password_hash="test-only",
            role="SUPERVISOR",
            store_id=data["store_id"],
            is_active=True,
        )
        db.add_all([foreign_shelf, actor])
        db.commit()
        foreign_shelf_id = foreign_shelf.id
        actor_id = actor.id

    with TestingSession() as db:
        actor = db.get(models.User, actor_id)
        monkeypatch.setattr(
            main_module,
            "_request_user",
            lambda _db, _request: actor,
        )
        with TestClient(app) as client:
            foreign = client.post(
                "/api/v1/shelf-images",
                data={"shelf_id": str(foreign_shelf_id)},
                files={"image": ("capture.jpg", b"invalid", "image/jpeg")},
            )
            missing = client.post(
                "/api/v1/shelf-images",
                data={"shelf_id": "2147483000"},
                files={"image": ("capture.jpg", b"invalid", "image/jpeg")},
            )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Shelf not found"}
    with TestingSession() as db:
        assert db.query(models.ShelfImage).filter_by(
            shelf_id=foreign_shelf_id
        ).count() == 0
