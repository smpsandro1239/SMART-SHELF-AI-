import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.main import app
from app.product_embedding_service import build_approved_product_registry

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


def test_approved_embedding_registry_is_isolated_by_source_store_and_excludes_unscoped_exemplars():
    previous_override = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    app.dependency_overrides[get_db] = override_get_db

    try:
        with TestClient(app) as client:
            store_a = client.post(
                "/api/v1/stores",
                json={"code": "EMB-SCOPE-A", "name": "Embedding Store A"},
            ).json()
            store_b = client.post(
                "/api/v1/stores",
                json={"code": "EMB-SCOPE-B", "name": "Embedding Store B"},
            ).json()
            zone_a = client.post(
                "/api/v1/zones",
                json={"store_id": store_a["id"], "name": "Zone A"},
            ).json()
            zone_b = client.post(
                "/api/v1/zones",
                json={"store_id": store_b["id"], "name": "Zone B"},
            ).json()
            shelf_a = client.post(
                "/api/v1/shelves",
                json={"zone_id": zone_a["id"], "code": "A-01"},
            ).json()
            shelf_b = client.post(
                "/api/v1/shelves",
                json={"zone_id": zone_b["id"], "code": "B-01"},
            ).json()
            product_a = client.post(
                "/api/v1/products",
                json={"sku": "SKU-STORE-A", "name": "Product A"},
            ).json()
            product_b = client.post(
                "/api/v1/products",
                json={"sku": "SKU-STORE-B", "name": "Product B"},
            ).json()

        with TestingSession() as db:
            reviewer = models.User(
                email="embedding-store-scope-reviewer@example.test",
                full_name="Embedding reviewer",
                password_hash="test-only",
                role="ADMIN",
                is_active=True,
            )
            db.add(reviewer)
            db.flush()

            image_a = models.ShelfImage(
                shelf_id=shelf_a["id"],
                original_filename="store-a.jpg",
                storage_path="/tmp/store-a.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256="a" * 64,
                retention_status="ACTIVE",
            )
            image_b = models.ShelfImage(
                shelf_id=shelf_b["id"],
                original_filename="store-b.jpg",
                storage_path="/tmp/store-b.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256="b" * 64,
                retention_status="ACTIVE",
            )
            db.add_all([image_a, image_b])
            db.flush()

            db.add_all([
                models.ProductEmbeddingExemplar(
                    product_id=product_a["id"],
                    shelf_image_id=image_a.id,
                    embedding=[1.0, 0.0],
                    embedding_dimension=2,
                    model_version="store-scoped-v1",
                    image_sha256="a" * 64,
                    licence="store-owned-reference-image",
                    review_status="APPROVED",
                    reviewed_by_user_id=reviewer.id,
                    reviewed_at=models.utc_now(),
                ),
                models.ProductEmbeddingExemplar(
                    product_id=product_b["id"],
                    shelf_image_id=image_b.id,
                    embedding=[0.0, 1.0],
                    embedding_dimension=2,
                    model_version="store-scoped-v1",
                    image_sha256="b" * 64,
                    licence="store-owned-reference-image",
                    review_status="APPROVED",
                    reviewed_by_user_id=reviewer.id,
                    reviewed_at=models.utc_now(),
                ),
                /* An approved exemplar without a source image has no
                   trustworthy store lineage and must never enter a
                   store-specific worker registry. */
                models.ProductEmbeddingExemplar(
                    product_id=product_b["id"],
                    shelf_image_id=None,
                    embedding=[0.7, 0.7],
                    embedding_dimension=2,
                    model_version="store-scoped-v1",
                    image_sha256="c" * 64,
                    licence="admin-approved-unscoped-reference",
                    review_status="APPROVED",
                    reviewed_by_user_id=reviewer.id,
                    reviewed_at=models.utc_now(),
                ),
            ])
            db.commit()

            registry_a = build_approved_product_registry(
                db,
                model_version="store-scoped-v1",
                store_id=store_a["id"],
                minimum_similarity=0.8,
            )
            registry_b = build_approved_product_registry(
                db,
                model_version="store-scoped-v1",
                store_id=store_b["id"],
                minimum_similarity=0.8,
            )

            match_a = registry_a.match([1.0, 0.0])
            cross_store_a = registry_a.match([0.0, 1.0])
            match_b = registry_b.match([0.0, 1.0])
            cross_store_b = registry_b.match([1.0, 0.0])

            assert match_a.status == "MATCHED"
            assert match_a.product_id == product_a["id"]
            assert cross_store_a.status == "UNKNOWN"
            assert cross_store_a.product_id is None
            assert match_b.status == "MATCHED"
            assert match_b.product_id == product_b["id"]
            assert cross_store_b.status == "UNKNOWN"
            assert cross_store_b.product_id is None
            assert len(registry_a._exemplars) == 1
            assert len(registry_b._exemplars) == 1
    finally:
        if previous_override is None:
            app.dependency_overrides.pop(get_db, None)
        else:
            app.dependency_overrides[get_db] = previous_override
        Base.metadata.drop_all(bind=TEST_ENGINE)
