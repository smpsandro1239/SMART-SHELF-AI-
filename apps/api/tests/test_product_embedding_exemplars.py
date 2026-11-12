import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import models  # noqa: F401
from app.main import app

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


def create_product(client):
    response = client.post(
        "/api/v1/products",
        json={"sku": "SKU-REF-001", "name": "Produto de referência"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def exemplar_payload(product_id, **overrides):
    payload = {
        "product_id": product_id,
        "embedding": [0.25, 0.5, 0.75],
        "model_version": "embedding-model-v1",
        "image_sha256": "a" * 64,
        "licence": "store-owned-reference-image",
    }
    payload.update(overrides)
    return payload


def test_exemplar_is_created_pending_and_embedding_is_not_exposed():
    with TestClient(app) as client:
        product_id = create_product(client)
        response = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id),
        )

        assert response.status_code == 201
        body = response.json()
        assert body["review_status"] == "PENDING"
        assert body["embedding_dimension"] == 3
        assert body["reviewed_at"] is None
        assert "embedding" not in body


def test_exemplar_can_be_approved_with_review_metadata():
    with TestClient(app) as client:
        product_id = create_product(client)
        created = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id),
        )
        exemplar_id = created.json()["id"]

        reviewed = client.patch(
            f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
            json={"review_status": "APPROVED", "review_notes": "Imagem e SKU confirmados"},
        )

        assert reviewed.status_code == 200
        assert reviewed.json()["review_status"] == "APPROVED"
        assert reviewed.json()["reviewed_at"] is not None
        assert reviewed.json()["review_notes"] == "Imagem e SKU confirmados"


def test_reviewed_exemplar_cannot_be_reviewed_twice():
    with TestClient(app) as client:
        product_id = create_product(client)
        created = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id),
        )
        exemplar_id = created.json()["id"]
        first = client.patch(
            f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
            json={"review_status": "REJECTED"},
        )
        second = client.patch(
            f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
            json={"review_status": "APPROVED"},
        )

        assert first.status_code == 200
        assert second.status_code == 409


def test_duplicate_product_model_and_image_is_rejected():
    with TestClient(app) as client:
        product_id = create_product(client)
        payload = exemplar_payload(product_id)
        first = client.post("/api/v1/product-embedding-exemplars", json=payload)
        duplicate = client.post("/api/v1/product-embedding-exemplars", json=payload)

        assert first.status_code == 201
        assert duplicate.status_code == 409


def test_exemplar_requires_valid_nonzero_finite_embedding():
    with TestClient(app) as client:
        product_id = create_product(client)
        zero = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id, embedding=[0, 0, 0]),
        )
        non_finite = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id, embedding=[1, "NaN", 2]),
        )

        assert zero.status_code == 422
        assert non_finite.status_code == 422


def test_source_image_hash_must_match_uploaded_image_record():
    with TestClient(app) as client:
        product_id = create_product(client)
        store = client.post("/api/v1/stores", json={"code": "IMG-01", "name": "Loja imagens"}).json()
        zone = client.post("/api/v1/zones", json={"store_id": store["id"], "name": "Zona"}).json()
        shelf = client.post("/api/v1/shelves", json={"zone_id": zone["id"], "code": "S-01"}).json()
        image = models.ShelfImage(
            shelf_id=shelf["id"],
            original_filename="source.jpg",
            storage_path="/tmp/source.jpg",
            mime_type="image/jpeg",
            file_size_bytes=3,
            sha256="b" * 64,
        )
        db = TestingSession()
        db.add(image)
        db.commit()
        db.refresh(image)
        image_id = image.id
        db.close()

        response = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id, shelf_image_id=image_id, image_sha256="c" * 64),
        )

        assert response.status_code == 422



def test_matching_registry_loads_only_approved_reviewed_exemplars():
    from app.product_embedding_service import build_approved_product_registry

    with TestClient(app) as client:
        product_id = create_product(client)
        approved = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id),
        ).json()
        pending = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(
                product_id,
                image_sha256="d" * 64,
                embedding=[0, 1, 0],
            ),
        ).json()

        db = TestingSession()
        reviewer = models.User(
            email="reviewer@example.test",
            full_name="Revisor",
            password_hash="test-hash",
            role="ADMIN",
            is_active=True,
        )
        db.add(reviewer)
        db.commit()
        db.refresh(reviewer)
        approved_row = db.get(models.ProductEmbeddingExemplar, approved["id"])
        approved_row.review_status = "APPROVED"
        approved_row.reviewed_by_user_id = reviewer.id
        approved_row.reviewed_at = models.utc_now()
        rejected_row = db.get(models.ProductEmbeddingExemplar, pending["id"])
        rejected_row.review_status = "REJECTED"
        rejected_row.reviewed_by_user_id = reviewer.id
        rejected_row.reviewed_at = models.utc_now()
        db.commit()

        registry = build_approved_product_registry(
            db,
            model_version="embedding-model-v1",
            minimum_similarity=0.8,
        )
        result = registry.match([0.25, 0.5, 0.75])

        assert result.status == "MATCHED"
        assert result.product_id == product_id
        db.close()


def test_matching_registry_does_not_load_pending_or_other_model_exemplars():
    from app.product_embedding_service import build_approved_product_registry

    with TestClient(app) as client:
        product_id = create_product(client)
        client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id),
        )
        db = TestingSession()
        registry = build_approved_product_registry(
            db,
            model_version="embedding-model-v1",
        )
        result = registry.match([0.25, 0.5, 0.75])

        assert result.status == "UNKNOWN"
        db.close()
