import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
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
            peer_reviewer = models.User(
                email="embedding-peer-reviewer@example.test",
                full_name="Revisor independente",
                password_hash="test-only-not-used",
                role="SUPERVISOR",
                store_id=own_store_id,
                is_active=True,
            )
            db.add_all([actor, peer_reviewer])
            db.commit()
            db.refresh(actor)
            db.refresh(peer_reviewer)

            created_exemplar = db.get(models.ProductEmbeddingExemplar, own_created.json()["id"])
            created_exemplar.created_by_user_id = actor.id
            db.commit()

            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: actor)

            listed = client.get("/api/v1/product-embedding-exemplars")
            assert listed.status_code == 200
            assert [item["id"] for item in listed.json()] == [own_created.json()["id"]]

            foreign_review = client.patch(
                f"/api/v1/product-embedding-exemplars/{foreign_created.json()['id']}/review",
                json={"review_status": "REJECTED", "review_notes": "Tentativa cross-store"},
            )
            assert foreign_review.status_code == 403

            self_review = client.patch(
                f"/api/v1/product-embedding-exemplars/{own_created.json()['id']}/review",
                json={"review_status": "APPROVED", "review_notes": "Tentativa de autoaprovação"},
            )
            assert self_review.status_code == 403

            monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: peer_reviewer)
            peer_review = client.patch(
                f"/api/v1/product-embedding-exemplars/{own_created.json()['id']}/review",
                json={"review_status": "APPROVED", "review_notes": "Origem verificada por revisor independente"},
            )
            assert peer_review.status_code == 200
            assert peer_review.json()["review_status"] == "APPROVED"

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




def test_inactive_product_exemplars_are_excluded_from_matching_registry():
    from app.product_embedding_service import build_approved_product_registry

    with TestClient(app) as client:
        active_product = client.post(
            "/api/v1/products",
            json={"sku": "SKU-ACTIVE-REGISTRY", "name": "Produto ativo"},
        )
        inactive_product = client.post(
            "/api/v1/products",
            json={"sku": "SKU-INACTIVE-REGISTRY", "name": "Produto desativado"},
        )
        assert active_product.status_code == 201
        assert inactive_product.status_code == 201

        active_exemplar = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(
                active_product.json()["id"],
                embedding=[1.0, 0.0, 0.0],
                image_sha256="1" * 64,
            ),
        )
        inactive_exemplar = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(
                inactive_product.json()["id"],
                embedding=[0.0, 1.0, 0.0],
                image_sha256="2" * 64,
            ),
        )
        assert active_exemplar.status_code == 201
        assert inactive_exemplar.status_code == 201

        with TestingSession() as db:
            reviewer = models.User(
                email="inactive-product-registry-reviewer@example.test",
                full_name="Embedding reviewer",
                password_hash="test-only-not-used",
                role="ADMIN",
                is_active=True,
            )
            db.add(reviewer)
            db.flush()
            for exemplar_id in (
                active_exemplar.json()["id"],
                inactive_exemplar.json()["id"],
            ):
                exemplar = db.get(models.ProductEmbeddingExemplar, exemplar_id)
                exemplar.review_status = "APPROVED"
                exemplar.reviewed_by_user_id = reviewer.id
                exemplar.reviewed_at = models.utc_now()
            inactive = db.get(models.Product, inactive_product.json()["id"])
            inactive.is_active = False
            db.commit()

            registry = build_approved_product_registry(
                db,
                model_version="embedding-model-v1",
                minimum_similarity=0.8,
                minimum_margin=0.05,
            )
            result = registry.match([0.0, 1.0, 0.0])

            assert result.status == "UNKNOWN"
            assert result.product_id is None
            active_result = registry.match([1.0, 0.0, 0.0])
            assert active_result.status == "MATCHED"
            assert active_result.product_id == active_product.json()["id"]


def test_inactive_product_exemplar_cannot_be_approved_but_can_be_rejected():
    with TestClient(app) as client:
        product_id = create_product(client)
        created = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id),
        )
        assert created.status_code == 201
        exemplar_id = created.json()["id"]

        with TestingSession() as db:
            product = db.get(models.Product, product_id)
            product.is_active = False
            db.commit()

        approval = client.patch(
            f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
            json={"review_status": "APPROVED", "review_notes": "Produto desativado"},
        )
        assert approval.status_code == 409
        assert "Inactive products" in approval.json()["detail"]

        with TestingSession() as db:
            exemplar = db.get(models.ProductEmbeddingExemplar, exemplar_id)
            assert exemplar.review_status == "PENDING"
            assert exemplar.reviewed_at is None

        rejection = client.patch(
            f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
            json={"review_status": "REJECTED", "review_notes": "SKU desativado"},
        )
        assert rejection.status_code == 200
        assert rejection.json()["review_status"] == "REJECTED"


def test_inactive_product_cannot_receive_new_embedding_exemplar():
    with TestClient(app) as client:
        product_id = create_product(client)
        with TestingSession() as db:
            product = db.get(models.Product, product_id)
            product.is_active = False
            db.commit()

        response = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id, image_sha256="3" * 64),
        )

        assert response.status_code == 404
        assert response.json()["detail"] == "Active product not found"

def test_matching_registry_refreshes_source_image_state_after_lock():
    from app.product_embedding_service import build_approved_product_registry

    with TestClient(app) as client:
        product_id = create_product(client)
        store = client.post(
            "/api/v1/stores",
            json={"code": "EMB-STALE-IMAGE", "name": "Loja imagem stale"},
        ).json()
        zone = client.post(
            "/api/v1/zones",
            json={"store_id": store["id"], "name": "Zona"},
        ).json()
        shelf = client.post(
            "/api/v1/shelves",
            json={"zone_id": zone["id"], "code": "S-STALE"},
        ).json()

        with TestingSession() as setup_db:
            image = models.ShelfImage(
                shelf_id=shelf["id"],
                original_filename="stale-source.jpg",
                storage_path="/tmp/stale-source.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256="f" * 64,
                retention_status="ACTIVE",
            )
            reviewer = models.User(
                email="stale-source-reviewer@example.test",
                full_name="Embedding reviewer",
                password_hash="test-only-not-used",
                role="ADMIN",
                is_active=True,
            )
            setup_db.add_all([image, reviewer])
            setup_db.commit()
            image_id, reviewer_id = image.id, reviewer.id

        created = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(
                product_id,
                shelf_image_id=image_id,
                image_sha256="f" * 64,
            ),
        )
        assert created.status_code == 201, created.text

        with TestingSession() as setup_db:
            exemplar = setup_db.get(
                models.ProductEmbeddingExemplar,
                created.json()["id"],
            )
            exemplar.review_status = "APPROVED"
            exemplar.reviewed_by_user_id = reviewer_id
            exemplar.reviewed_at = models.utc_now()
            setup_db.commit()

        with TestingSession() as db:
            stale_identity = db.get(models.ShelfImage, image_id)
            assert stale_identity.retention_status == "ACTIVE"

            db.query(models.ShelfImage).filter(
                models.ShelfImage.id == image_id
            ).update(
                {models.ShelfImage.retention_status: "RESTRICTED"},
                synchronize_session=False,
            )

            registry = build_approved_product_registry(
                db,
                model_version="embedding-model-v1",
                minimum_similarity=0.8,
                minimum_margin=0.05,
            )

            assert stale_identity.retention_status == "RESTRICTED"
            result = registry.match([0.25, 0.5, 0.75])
            assert result.status == "UNKNOWN"
            assert result.product_id is None




def test_registry_skips_approved_exemplars_with_inconsistent_stored_dimension():
    from app.product_embedding_service import build_approved_product_registry

    with TestClient(app) as client:
        product_id = create_product(client)
        valid = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id),
        )
        corrupt = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(
                product_id,
                image_sha256="b" * 64,
                embedding=[0.75, 0.5, 0.25],
            ),
        )
        assert valid.status_code == 201
        assert corrupt.status_code == 201

        with TestingSession() as db:
            reviewer = models.User(
                email="embedding-integrity-reviewer@example.test",
                full_name="Revisor integridade",
                password_hash="test-hash",
                role="ADMIN",
                is_active=True,
            )
            db.add(reviewer)
            db.commit()
            db.refresh(reviewer)

            for exemplar_id in (valid.json()["id"], corrupt.json()["id"]):
                row = db.get(models.ProductEmbeddingExemplar, exemplar_id)
                row.review_status = "APPROVED"
                row.reviewed_by_user_id = reviewer.id
                row.reviewed_at = models.utc_now()
            db.get(
                models.ProductEmbeddingExemplar, corrupt.json()["id"]
            ).embedding_dimension = 128
            db.commit()

            registry = build_approved_product_registry(
                db,
                model_version="embedding-model-v1",
                minimum_similarity=0.8,
            )
            result = registry.match([0.25, 0.5, 0.75])

            assert result.status == "MATCHED"
            assert result.product_id == product_id
            assert len(registry._exemplars) == 1


def test_exemplar_rejects_blank_model_version_and_licence():
    with TestClient(app) as client:
        product_id = create_product(client)
        blank_version = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id, model_version="   "),
        )
        blank_licence = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id, licence="   "),
        )

        assert blank_version.status_code == 422
        assert blank_licence.status_code == 422



def test_cosine_similarity_handles_large_finite_vectors_without_overflow():
    from app.product_matching import ProductEmbeddingRegistry, ProductExemplar

    exemplar = ProductExemplar(
        product_id=1,
        embedding=(1e308, 1e308, 1e308),
        model_version="embedding-model-v1",
        image_sha256="a" * 64,
        reviewed_by="reviewer@example.test",
        reviewed_at="2026-11-16T00:00:00+00:00",
        licence="store-owned-reference-image",
    )
    registry = ProductEmbeddingRegistry(
        [exemplar],
        model_version="embedding-model-v1",
        minimum_similarity=0.99,
    )

    result = registry.match([1e308, 1e308, 1e308])

    assert result.status == "MATCHED"
    assert result.similarity == pytest.approx(1.0)


def test_registry_builder_rejects_blank_model_version():
    from app.product_embedding_service import build_approved_product_registry

    with TestingSession() as db:
        with pytest.raises(ValueError, match="model_version is required"):
            build_approved_product_registry(db, model_version="   ")



def test_embedding_domain_rejects_boolean_components():
    from app.product_matching import ProductExemplar

    with pytest.raises(ValueError, match="booleans are not valid"):
        ProductExemplar(
            product_id=1,
            embedding=(True, 0.5, 0.75),
            model_version="embedding-model-v1",
            image_sha256="a" * 64,
            reviewed_by="reviewer@example.test",
            reviewed_at="2026-11-16T00:00:00+00:00",
            licence="store-owned-reference-image",
        )


def test_registry_abstains_when_one_model_version_has_conflicting_dimensions():
    from app.product_embedding_service import build_approved_product_registry

    with TestClient(app) as client:
        product_id = create_product(client)
        first = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id),
        )
        second = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(
                product_id,
                embedding=[0.5, 0.5],
                image_sha256="e" * 64,
            ),
        )
        assert first.status_code == 201
        assert second.status_code == 201

        with TestingSession() as db:
            reviewer = models.User(
                email="dimension-reviewer@example.test",
                full_name="Revisor dimensões",
                password_hash="test-hash",
                role="ADMIN",
                is_active=True,
            )
            db.add(reviewer)
            db.commit()
            db.refresh(reviewer)
            for item_id in (first.json()["id"], second.json()["id"]):
                row = db.get(models.ProductEmbeddingExemplar, item_id)
                row.review_status = "APPROVED"
                row.reviewed_by_user_id = reviewer.id
                row.reviewed_at = models.utc_now()
            db.commit()

            registry = build_approved_product_registry(
                db,
                model_version="embedding-model-v1",
                minimum_similarity=0.8,
            )
            result = registry.match([0.25, 0.5, 0.75])

            assert registry._exemplars == ()
            assert result.status == "UNKNOWN"
            assert result.product_id is None



def test_matching_registry_skips_exemplar_when_source_image_hash_changes():
    from app.product_embedding_service import build_approved_product_registry

    with TestClient(app) as client:
        product_id = create_product(client)
        store = client.post(
            "/api/v1/stores",
            json={"code": "EMB-HASH-CHANGE", "name": "Loja hash alterado"},
        ).json()
        zone = client.post(
            "/api/v1/zones",
            json={"store_id": store["id"], "name": "Zona"},
        ).json()
        shelf = client.post(
            "/api/v1/shelves",
            json={"zone_id": zone["id"], "code": "S-HASH"},
        ).json()

        original_hash = "a" * 64
        with TestingSession() as setup_db:
            image = models.ShelfImage(
                shelf_id=shelf["id"],
                original_filename="source-hash.jpg",
                storage_path="/tmp/source-hash.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256=original_hash,
                retention_status="ACTIVE",
            )
            reviewer = models.User(
                email="hash-change-reviewer@example.test",
                full_name="Embedding reviewer",
                password_hash="test-only-not-used",
                role="ADMIN",
                is_active=True,
            )
            setup_db.add_all([image, reviewer])
            setup_db.commit()
            image_id, reviewer_id = image.id, reviewer.id

        created = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(
                product_id,
                shelf_image_id=image_id,
                image_sha256=original_hash,
            ),
        )
        assert created.status_code == 201, created.text

        with TestingSession() as setup_db:
            row = setup_db.get(
                models.ProductEmbeddingExemplar,
                created.json()["id"],
            )
            row.review_status = "APPROVED"
            row.reviewed_by_user_id = reviewer_id
            row.reviewed_at = models.utc_now()
            setup_db.commit()

        with TestingSession() as db:
            db.query(models.ShelfImage).filter(
                models.ShelfImage.id == image_id
            ).update(
                {models.ShelfImage.sha256: "b" * 64},
                synchronize_session=False,
            )

            registry = build_approved_product_registry(
                db,
                model_version="embedding-model-v1",
                minimum_similarity=0.8,
            )
            result = registry.match([0.25, 0.5, 0.75])

            assert registry._exemplars == ()
            assert result.status == "UNKNOWN"
            assert result.product_id is None

def test_image_less_exemplar_non_admin_is_rejected_before_product_lock(monkeypatch):
    with TestClient(app) as client:
        product_id = create_product(client)
        created = client.post(
            "/api/v1/product-embedding-exemplars",
            json=exemplar_payload(product_id, image_sha256="7" * 64),
        )
        assert created.status_code == 201, created.text
        exemplar_id = created.json()["id"]

        with TestingSession() as db:
            creator = models.User(
                email="image-less-exemplar-creator@example.test",
                full_name="Criador",
                password_hash="test-only-not-used",
                role="ADMIN",
                is_active=True,
            )
            reviewer = models.User(
                email="image-less-exemplar-supervisor@example.test",
                full_name="Supervisor",
                password_hash="test-only-not-used",
                role="SUPERVISOR",
                is_active=True,
            )
            db.add_all([creator, reviewer])
            db.flush()
            row = db.get(models.ProductEmbeddingExemplar, exemplar_id)
            row.created_by_user_id = creator.id
            reviewer_id = reviewer.id
            db.commit()

        monkeypatch.setattr(
            main_module,
            "_request_user",
            lambda request_db, _request: request_db.get(models.User, reviewer_id),
        )
        statements = []

        def capture_statement(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(TEST_ENGINE, "before_cursor_execute", capture_statement)
        try:
            response = client.patch(
                f"/api/v1/product-embedding-exemplars/{exemplar_id}/review",
                json={"review_status": "REJECTED", "review_notes": "Revisão não autorizada"},
            )
        finally:
            event.remove(TEST_ENGINE, "before_cursor_execute", capture_statement)

        assert response.status_code == 403
        assert not any("from products" in statement for statement in statements), (
            "A revisão não autorizada não pode consultar/bloquear o produto antes da recusa"
        )
        with TestingSession() as db:
            stored = db.get(models.ProductEmbeddingExemplar, exemplar_id)
            assert stored.review_status == "PENDING"
            assert stored.reviewed_at is None
