"""Verify reviewed SKU evaluation isolation on PostgreSQL 16 using real JWTs.

Creates reviewed detections in two stores and exercises the HTTP endpoint through
PostgreSQL-backed sessions. Supervisors must see only their own store, ADMIN may
see both stores, and EMPLOYEE must be denied.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def _bearer(user_id: int, role: str) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def main() -> None:
    suffix = uuid4().hex[:12]
    reviewed_at = datetime.now(timezone.utc)
    db = SessionLocal()
    try:
        store_a = models.Store(code=f"PG-SKU-EVAL-A-{suffix}", name="SKU evaluation store A")
        store_b = models.Store(code=f"PG-SKU-EVAL-B-{suffix}", name="SKU evaluation store B")
        product = models.Product(sku=f"PG-SKU-EVAL-{suffix}", name="SKU evaluation product", is_active=True)
        db.add_all([store_a, store_b, product])
        db.flush()

        zone_a = models.Zone(store_id=store_a.id, name="Evaluation zone A")
        zone_b = models.Zone(store_id=store_b.id, name="Evaluation zone B")
        db.add_all([zone_a, zone_b])
        db.flush()
        shelf_a = models.Shelf(zone_id=zone_a.id, code=f"SKU-EVAL-A-{suffix}")
        shelf_b = models.Shelf(zone_id=zone_b.id, code=f"SKU-EVAL-B-{suffix}")
        db.add_all([shelf_a, shelf_b])
        db.flush()

        supervisor = models.User(
            email=f"pg-sku-eval-supervisor-{suffix}@example.test",
            full_name="SKU evaluation supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store_a.id,
            is_active=True,
        )
        admin = models.User(
            email=f"pg-sku-eval-admin-{suffix}@example.test",
            full_name="SKU evaluation admin",
            password_hash="smoke-test-only",
            role="ADMIN",
            store_id=None,
            is_active=True,
        )
        employee = models.User(
            email=f"pg-sku-eval-employee-{suffix}@example.test",
            full_name="SKU evaluation employee",
            password_hash="smoke-test-only",
            role="EMPLOYEE",
            store_id=store_a.id,
            is_active=True,
        )
        db.add_all([supervisor, admin, employee])
        db.flush()

        for label, shelf in (("A", shelf_a), ("B", shelf_b)):
            model_version = f"embed-store-{label.lower()}-pg-smoke-v1"
            image = models.ShelfImage(
                shelf_id=shelf.id,
                original_filename=f"sku-evaluation-{label}.jpg",
                storage_path=f"/tmp/pg-sku-evaluation-{suffix}-{label}.jpg",
                mime_type="image/jpeg",
                file_size_bytes=128,
                sha256=("a" if label == "A" else "b") * 64,
                analysis_status="COMPLETED",
                model_version="detector-pg-smoke-v1",
                retention_status="ACTIVE",
            )
            db.add(image)
            db.flush()
            detection = models.ShelfImageDetection(
                shelf_image_id=image.id,
                product_id=product.id,
                label="product",
                confidence=0.98,
                x_min=0.1,
                y_min=0.1,
                x_max=0.8,
                y_max=0.8,
                model_version="detector-pg-smoke-v1",
                embedding_model_version=model_version,
                sku_match_status="MATCHED",
            )
            db.add(detection)
            db.flush()
            run = models.ShelfImageOCRRun(
                shelf_image_id=image.id,
                provider="sku-evaluation-pg-smoke",
                model_version="ocr-pg-smoke-v1",
                status="COMPLETED",
                created_at=reviewed_at - timedelta(minutes=2),
            )
            db.add(run)
            db.flush()
            db.add(models.DetectionSkuReview(
                detection_id=detection.id,
                previous_product_id=product.id,
                selected_product_id=product.id,
                decision="CONFIRMED",
                reviewer_user_id=admin.id,
                created_at=reviewed_at,
            ))
            db.add(models.ShelfImageFusedEvidence(
                ocr_run_id=run.id,
                detection_id=detection.id,
                status="CONSENSUS",
                suggested_product_id=product.id,
                visual_product_id=product.id,
                text_product_id=None,
                visual_status="MATCHED",
                text_status="UNKNOWN",
                visual_similarity=0.98,
                text_score=None,
                ocr_confidence=0.9,
                visual_model_version=model_version,
                ocr_provider="sku-evaluation-pg-smoke",
                ocr_model_version="ocr-pg-smoke-v1",
                reason=f"PostgreSQL SKU evaluation fixture for store {label}",
                created_at=reviewed_at - timedelta(minutes=1),
            ))
        db.commit()

        store_a_id = store_a.id
        store_b_id = store_b.id
        supervisor_id = supervisor.id
        admin_id = admin.id
        employee_id = employee.id
    finally:
        db.close()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    try:
        with TestClient(app) as client:
            supervisor_headers = _bearer(supervisor_id, "SUPERVISOR")
            admin_headers = _bearer(admin_id, "ADMIN")
            employee_headers = _bearer(employee_id, "EMPLOYEE")

            own_store = client.get(
                "/api/v1/sku-evaluation/reviewed",
                headers=supervisor_headers,
            )
            assert own_store.status_code == 200, own_store.text
            own_report = own_store.json()
            assert own_report["store_id"] == store_a_id, own_report
            assert own_report["sample_count"] == 1, own_report
            assert set(own_report["by_model_version"]) == {
                "embed-store-a-pg-smoke-v1"
            }, own_report

            foreign_filter = client.get(
                "/api/v1/sku-evaluation/reviewed",
                params={"store_id": store_b_id},
                headers=supervisor_headers,
            )
            assert foreign_filter.status_code == 403, foreign_filter.text

            global_report = client.get(
                "/api/v1/sku-evaluation/reviewed",
                headers=admin_headers,
            )
            assert global_report.status_code == 200, global_report.text
            admin_report = global_report.json()
            assert admin_report["store_id"] is None, admin_report
            assert admin_report["sample_count"] == 2, admin_report
            assert set(admin_report["by_model_version"]) == {
                "embed-store-a-pg-smoke-v1",
                "embed-store-b-pg-smoke-v1",
            }, admin_report

            employee_response = client.get(
                "/api/v1/sku-evaluation/reviewed",
                headers=employee_headers,
            )
            assert employee_response.status_code == 403, employee_response.text
    finally:
        main_module.settings = original_settings

    print(
        "PostgreSQL reviewed SKU evaluation smoke passed: "
        "SUPERVISOR saw one own-store sample, foreign-store filter was denied, "
        "ADMIN saw both stores, and EMPLOYEE was denied."
    )


if __name__ == "__main__":
    main()
