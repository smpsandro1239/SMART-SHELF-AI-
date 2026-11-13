import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from types import SimpleNamespace
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models
from app.main import app

ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


def override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_database():
    previous = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous
    Base.metadata.drop_all(bind=ENGINE)


def seed_reviewed_detections():
    db = Session()
    store = models.Store(code="TRAIN-01", name="Training store")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Zone")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="S-01")
    db.add(shelf)
    db.flush()
    product = models.Product(sku="SKU-TRAIN-1", name="Product one", is_active=True)
    db.add(product)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf.id, original_filename="capture.jpg",
        storage_path="/tmp/training-capture.jpg", mime_type="image/jpeg",
        file_size_bytes=100, sha256="e" * 64,
    )
    db.add(image)
    db.flush()

    def detection(label):
        item = models.ShelfImageDetection(
            shelf_image_id=image.id, product_id=product.id, label=label,
            confidence=0.9, x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
            model_version="detector-v1", sku_match_status="MATCHED",
        )
        db.add(item)
        db.flush()
        return item

    eligible = detection("confirmed")
    excluded = detection("rejected-later")
    db.add_all([
        models.DetectionSkuReview(
            detection_id=eligible.id, previous_product_id=product.id,
            selected_product_id=product.id, decision="CONFIRMED",
        ),
        models.DetectionSkuReview(
            detection_id=excluded.id, previous_product_id=product.id,
            selected_product_id=None, decision="REJECTED",
        ),
    ])
    db.commit()
    result = {"eligible_id": eligible.id, "excluded_id": excluded.id, "product_id": product.id, "image_id": image.id, "store_id": store.id}
    db.close()
    return result


def test_only_latest_confirmed_or_corrected_reviews_are_candidates():
    data = seed_reviewed_detections()
    with TestClient(app) as client:
        response = client.get("/api/v1/training-candidates/reviewed")
    assert response.status_code == 200
    rows = response.json()
    assert [row["detection_id"] for row in rows] == [data["eligible_id"]]
    candidate = rows[0]
    assert candidate["decision"] == "CONFIRMED"
    assert candidate["product_id"] == data["product_id"]
    assert candidate["dataset_status"] == "CANDIDATE"
    assert candidate["requires_exemplar_approval"] is True
    assert candidate["capture_group_key"] == f"image:{'e' * 64}"


def test_latest_rejection_removes_previous_confirmation_from_candidates():
    data = seed_reviewed_detections()
    db = Session()
    db.add(models.DetectionSkuReview(
        detection_id=data["eligible_id"], previous_product_id=data["product_id"],
        selected_product_id=None, decision="REJECTED",
    ))
    db.commit()
    db.close()

    with TestClient(app) as client:
        response = client.get("/api/v1/training-candidates/reviewed")
    assert response.status_code == 200
    assert response.json() == []


def test_candidate_is_not_repeated_when_image_is_already_an_exemplar():
    data = seed_reviewed_detections()
    db = Session()
    db.add(models.ProductEmbeddingExemplar(
        product_id=data["product_id"], shelf_image_id=None,
        embedding=[1.0, 0.0], embedding_dimension=2,
        model_version="embedding-v1", image_sha256="e" * 64,
        licence="store-owned",
        review_status="REJECTED",
    ))
    db.commit()
    db.close()

    with TestClient(app) as client:
        response = client.get("/api/v1/training-candidates/reviewed")
    assert response.status_code == 200
    assert response.json() == []



def test_restricted_image_is_not_exposed_as_training_candidate():
    data = seed_reviewed_detections()
    db = Session()
    image = db.get(models.ShelfImage, data["image_id"])
    image.retention_status = "RESTRICTED"
    db.commit()
    db.close()

    with TestClient(app) as client:
        response = client.get("/api/v1/training-candidates/reviewed")

    assert response.status_code == 200
    assert response.json() == []



def test_training_candidates_are_scoped_to_supervisors_store(monkeypatch):
    data = seed_reviewed_detections()
    db = Session()
    foreign_store = models.Store(code="TRAIN-FOREIGN", name="Foreign store")
    db.add(foreign_store)
    db.commit()
    foreign_store_id = foreign_store.id
    db.close()

    from app import main as main_module
    monkeypatch.setattr(
        main_module,
        "_request_user",
        lambda _db, _request: SimpleNamespace(
            id=9001, role="SUPERVISOR", store_id=foreign_store_id
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/training-candidates/reviewed")

    assert response.status_code == 200
    assert response.json() == []


def test_training_candidates_remain_visible_to_their_own_store_supervisor(monkeypatch):
    data = seed_reviewed_detections()

    from app import main as main_module
    monkeypatch.setattr(
        main_module,
        "_request_user",
        lambda _db, _request: SimpleNamespace(
            id=9002, role="SUPERVISOR", store_id=data["store_id"]
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/training-candidates/reviewed")

    assert response.status_code == 200
    assert [row["detection_id"] for row in response.json()] == [data["eligible_id"]]


def test_reviewed_sku_evaluation_rejects_foreign_store_filter(monkeypatch):
    data = seed_reviewed_detections()
    db = Session()
    foreign_store = models.Store(code="EVAL-FOREIGN", name="Foreign evaluation store")
    db.add(foreign_store)
    db.commit()
    foreign_store_id = foreign_store.id
    db.close()

    from app import main as main_module
    monkeypatch.setattr(
        main_module,
        "_request_user",
        lambda _db, _request: SimpleNamespace(
            id=9003, role="SUPERVISOR", store_id=data["store_id"]
        ),
    )

    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/sku-evaluation/reviewed?store_id={foreign_store_id}"
        )

    assert response.status_code == 403


def test_reviewed_sku_evaluation_defaults_to_supervisors_store(monkeypatch):
    data = seed_reviewed_detections()

    from app import main as main_module
    monkeypatch.setattr(
        main_module,
        "_request_user",
        lambda _db, _request: SimpleNamespace(
            id=9004, role="SUPERVISOR", store_id=data["store_id"]
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/v1/sku-evaluation/reviewed")

    assert response.status_code == 200
    assert response.json()["store_id"] == data["store_id"]
