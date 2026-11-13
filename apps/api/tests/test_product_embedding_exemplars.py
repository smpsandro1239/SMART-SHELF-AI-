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
from app import main as main_module

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



def test_embedding_exemplars_are_scoped_to_source_image_store(monkeypatch):
    with TestClient(app) as client:
        product_id = create_product(client)

        def create_source_image(code, digest):
            store = client.post("/api/v1/stores", json={
                "code": code, "name": f"Loja {code}",
            }).json()
            zone = client.post("/api/v1/zones", json={
                "store_id": store["id"], "name": "Zona",
            }).json()
            shelf = client.post("/api/v1/shelves", json={
                "zone_id": zone["id"], "code": "S-01",
            }).json()
            db = TestingSession()
            image = models.ShelfImage(
                shelf_id=shelf["id"],
                original_filename=f"{code}.jpg",
                storage_path=f"/tmp/{code}.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256=digest,
            )
            db.add(image)
            db.commit()
            db.refresh(image)
            result = (image.id, store["id"])
            db.close()
            return result

        own_digest = "e" * 64
        foreign_digest = "f" * 64
        own_image_id, own_store_id = create_source_image("EMB-OWN", own_digest)
        foreign_image_id, _ = create_source_image("EMB-FOREIGN", foreign_digest)

        own_created = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(
                product_id, shelf_image_id=own_image_id, image_sha256=own_digest,
            ),
        )
        foreign_created = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(
                product_id, shelf_image_id=foreign_image_id, image_sha256=foreign_digest,
            ),
        )
        assert own_created.status_code == 201
        assert foreign_created.status_code == 201

        with TestingSession() as db:
            actor = models.User(
                email="embedding-scope-supervisor@example.test",
                full_name="Supervisor embeddings",
                password_hash="test-only-not-used",
                role="SUPERVISOR",
                store_id=own_store_id,
                is_active=True,
            )
            db.add(actor)
            db.commit()
            db.refresh(actor)
            actor_id = actor.id

        with TestingSession() as db:
            actor = db.get(models.User, actor_id)
            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

            listed = client.get("/api/v1/product-embedding-exemplars")
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()] == [own_created.json()["id"]]

            foreign_review = client.patch(
                f"/api/v1/product-embedding-exemplars/{foreign_created.json()['id']}/review",
                json={"review_status": "REJECTED", "review_notes": "Tentativa cross-store"},
            )
            assert foreign_review.status_code == 403

            own_review = client.patch(
                f"/api/v1/product-embedding-exemplars/{own_created.json()['id']}/review",
                json={"review_status": "APPROVED", "review_notes": "Origem verificada"},
            )
            assert own_review.status_code == 200

def test_restricted_source_image_blocks_embedding_exemplar_access_and_matching(monkeypatch):
    from app.product_embedding_service import build_approved_product_registry

    with TestClient(app) as client:
        product_id = create_product(client)
        store = client.post(
            "/api/v1/stores",
            json={"code": "EMB-RETENTION", "name": "Loja embeddings retenção"},
        ).json()
        zone = client.post(
            "/api/v1/zones",
            json={"store_id": store["id"], "name": "Zona"},
        ).json()
        shelf = client.post(
            "/api/v1/shelves",
            json={"zone_id": zone["id"], "code": "S-RET"},
        ).json()

        with TestingSession() as db:
            image = models.ShelfImage(
                shelf_id=shelf["id"],
                original_filename="retention-source.jpg",
                storage_path=f"/tmp/retention-source-{store['id']}.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256="9" * 64,
            )
            supervisor = models.User(
                email="embedding-retention-supervisor@example.test",
                full_name="Supervisor",
                password_hash="test-only-not-used",
                role="SUPERVISOR",
                store_id=store["id"],
                is_active=True,
            )
            reviewer = models.User(
                email="embedding-retention-reviewer@example.test",
                full_name="Reviewer",
                password_hash="test-only-not-used",
                role="ADMIN",
                is_active=True,
            )
            db.add_all([image, supervisor, reviewer])
            db.commit()
            db.refresh(image)
            db.refresh(supervisor)
            db.refresh(reviewer)
            image_id = image.id
            supervisor_id = supervisor.id
            reviewer_id = reviewer.id

        with TestingSession() as db:
            supervisor = db.get(models.User, supervisor_id)
            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: supervisor)

            created = client.post(
                "/api/v1/product-embedding-exemplars",
                json=exemplar_payload(
                    product_id,
                    shelf_image_id=image_id,
                    image_sha256="9" * 64,
                ),
            )
            assert created.status_code == 201
            exemplar_id = created.json()["id"]

            with TestingSession() as write_db:
                exemplar = write_db.get(models.ProductEmbeddingExemplar, exemplar_id)
                exemplar.review_status = "APPROVED"
                exemplar.reviewed_by_user_id = reviewer_id
                exemplar.reviewed_at = models.utc_now()
                source_image = write_db.get(models.ShelfImage, image_id)
                source_image.retention_status = "RESTRICTED"
                write_db.commit()

            listed = client.get("/api/v1/product-embedding-exemplars")
            assert listed.status_code == 200
            assert all(item["id"] != exemplar_id for item in listed.json())

            review = client.patch(
                f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
                json={"review_status": "REJECTED", "review_notes": "Retenção"},
            )
            assert review.status_code == 410

            new_exemplar = client.post(
                "/api/v1/product-embedding-exemplars",
                json=exemplar_payload(
                    product_id,
                    shelf_image_id=image_id,
                    image_sha256="9" * 64,
                    model_version="embedding-model-v2",
                ),
            )
            assert new_exemplar.status_code == 410

            registry = build_approved_product_registry(
                db,
                model_version="embedding-model-v1",
                minimum_similarity=0.8,
            )
            match = registry.match([0.25, 0.5, 0.75])
            assert match.status == "UNKNOWN"
            assert match.product_id is None

        with TestingSession() as db:
            exemplar = db.get(models.ProductEmbeddingExemplar, exemplar_id)
            assert exemplar.review_status == "APPROVED"
            assert exemplar.reviewed_by_user_id == reviewer_id

