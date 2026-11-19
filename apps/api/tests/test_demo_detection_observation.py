import os
from types import SimpleNamespace

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module, models
from app.database import Base, get_db
from app.main import app

ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSession = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()


def test_demo_detection_requires_human_review_and_is_idempotent(monkeypatch):
    previous_db_override = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    db = TestingSession()
    try:
        store = models.Store(code="DEMO-OBS-TEST", name="Demo observation test")
        db.add(store)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Demo zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code="DEMO-OBS-01")
        regression_shelf = models.Shelf(zone_id=zone.id, code="DEMO-OBS-REGRESSION")
        forged_shelf = models.Shelf(zone_id=zone.id, code="DEMO-OBS-FORGED")
        product = models.Product(sku="DEMO-OBS-SKU", name="Demo product")
        other_product = models.Product(sku="DEMO-OBS-OTHER", name="Other shelf product")
        reviewer = models.User(
            email="supervisor@demo-observation.test",
            full_name="Demo Supervisor",
            password_hash="not-used-in-this-test",
            role="SUPERVISOR",
            store_id=store.id,
            is_active=True,
        )
        employee = models.User(
            email="employee@demo-observation.test",
            full_name="Demo Employee",
            password_hash="not-used-in-this-test",
            role="EMPLOYEE",
            store_id=store.id,
            is_active=True,
        )
        db.add_all([shelf, regression_shelf, forged_shelf, product, other_product, reviewer, employee])
        db.flush()
        db.add_all([
            models.ShelfProduct(shelf_id=shelf.id, product_id=product.id, target_quantity=8, min_display_quantity=2),
            models.ShelfProduct(shelf_id=shelf.id, product_id=other_product.id, target_quantity=8, min_display_quantity=2),
            models.ShelfProduct(shelf_id=regression_shelf.id, product_id=product.id, target_quantity=8, min_display_quantity=2),
            models.ShelfProduct(shelf_id=regression_shelf.id, product_id=other_product.id, target_quantity=8, min_display_quantity=2),
            models.ShelfProduct(shelf_id=forged_shelf.id, product_id=product.id, target_quantity=8, min_display_quantity=2),
            models.InventorySnapshot(
                store_id=store.id,
                product_id=product.id,
                on_hand_quantity=12,
                reserved_quantity=0,
                source="MANUAL",
                external_reference="demo-observation-test-v1",
                captured_at=models.utc_now(),
            ),
        ])
        image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="synthetic.png",
            storage_path="/tmp/synthetic.png",
            mime_type="image/png",
            file_size_bytes=128,
            sha256="a" * 64,
            analysis_status="COMPLETED",
            model_version="mock-shelf-vision-v1",
            retention_status="ACTIVE",
        )
        db.add(image)
        db.flush()
        detection = models.ShelfImageDetection(
            shelf_image_id=image.id,
            label="empty_facing",
            confidence=0.95,
            x_min=0.1,
            y_min=0.2,
            x_max=0.4,
            y_max=0.6,
            model_version="mock-shelf-vision-v1",
        )
        regression_image = models.ShelfImage(
            shelf_id=regression_shelf.id,
            original_filename="synthetic-regression.png",
            storage_path="/tmp/synthetic-regression.png",
            mime_type="image/png",
            file_size_bytes=128,
            sha256="b" * 64,
            analysis_status="COMPLETED",
            model_version="mock-shelf-vision-v1",
            retention_status="ACTIVE",
        )
        db.add(regression_image)
        db.flush()
        regression_detection = models.ShelfImageDetection(
            shelf_image_id=regression_image.id,
            label="empty_facing",
            confidence=0.91,
            x_min=0.5,
            y_min=0.2,
            x_max=0.8,
            y_max=0.6,
            model_version="mock-shelf-vision-v1",
        )
        db.add_all([detection, regression_detection])
        db.commit()
        reviewer_id, employee_id = reviewer.id, employee.id
        store_id, shelf_id = store.id, shelf.id
        forged_shelf_id = forged_shelf.id
        product_id, other_product_id = product.id, other_product.id
        detection_id, regression_detection_id = detection.id, regression_detection.id
        regression_image_id = regression_image.id
    finally:
        db.close()

    app.dependency_overrides[get_db] = override_get_db
    actor = {
        "value": SimpleNamespace(
            id=reviewer_id, role="SUPERVISOR", store_id=store_id, full_name="Demo Supervisor"
        )
    }
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor["value"])

    try:
        with TestClient(app) as client:
            denied = client.post(
                f"/api/v1/shelf-image-detections/{detection_id}/observation",
                json={"product_id": product_id, "confirmed_status": "EMPTY"},
            )
            assert denied.status_code == 409
            assert "human SKU review" in denied.json()["detail"]

            db = TestingSession()
            try:
                db.add(models.DetectionSkuReview(
                    detection_id=detection_id,
                    selected_product_id=product_id,
                    decision="CORRECTED",
                    reviewer_user_id=reviewer_id,
                    notes="SKU escolhido pelo supervisor para o cenário sintético.",
                ))
                db.commit()
            finally:
                db.close()

            missing_status = client.post(
                f"/api/v1/shelf-image-detections/{detection_id}/observation",
                json={"product_id": product_id},
            )
            assert missing_status.status_code == 422

            mismatched_status = client.post(
                f"/api/v1/shelf-image-detections/{detection_id}/observation",
                json={"product_id": product_id, "confirmed_status": "LOW_STOCK"},
            )
            assert mismatched_status.status_code == 409
            assert "confirmed observation status" in mismatched_status.json()["detail"]

            executed_statements = []

            def record_statement(connection, cursor, statement, parameters, context, executemany):
                normalized = " ".join(statement.lower().split())
                if normalized.startswith("select") and (
                    "shelf_image_detections" in normalized or "shelf_images" in normalized
                ):
                    executed_statements.append(normalized)

            event.listen(ENGINE, "before_cursor_execute", record_statement)
            try:
                first = client.post(
                    f"/api/v1/shelf-image-detections/{detection_id}/observation",
                    json={"product_id": product_id, "confirmed_status": "EMPTY"},
                )
            finally:
                event.remove(ENGINE, "before_cursor_execute", record_statement)

            lock_order_queries = [
                "detection" if "shelf_image_detections" in statement else "image"
                for statement in executed_statements
            ]
            assert lock_order_queries[:3] == ["detection", "image", "detection"]

            second = client.post(
                f"/api/v1/shelf-image-detections/{detection_id}/observation",
                json={"product_id": product_id, "confirmed_status": "EMPTY"},
            )

            # A later SKU review must not make the original idempotency key
            # silently return an observation for a different product.
            db = TestingSession()
            try:
                db.add(models.DetectionSkuReview(
                    detection_id=regression_detection_id,
                    selected_product_id=product_id,
                    decision="CORRECTED",
                    reviewer_user_id=reviewer_id,
                    notes="Regressão: SKU inicial para a deteção isolada.",
                ))
                db.commit()
            finally:
                db.close()

            regression_first = client.post(
                f"/api/v1/shelf-image-detections/{regression_detection_id}/observation",
                json={"product_id": product_id, "confirmed_status": "EMPTY"},
            )
            db = TestingSession()
            try:
                db.add(models.DetectionSkuReview(
                    detection_id=regression_detection_id,
                    selected_product_id=other_product_id,
                    decision="CORRECTED",
                    reviewer_user_id=reviewer_id,
                    notes="Regressão: SKU revisto depois da observação inicial.",
                ))
                db.commit()
            finally:
                db.close()

            changed_product = client.post(
                f"/api/v1/shelf-image-detections/{regression_detection_id}/observation",
                json={"product_id": other_product_id, "confirmed_status": "EMPTY"},
            )
            changed_product = client.post(
                f"/api/v1/shelf-image-detections/{regression_detection_id}/observation",
                json={"product_id": other_product_id, "confirmed_status": "EMPTY"},
            )
            db = TestingSession()
            try:
                latest_regression_review = (
                    db.query(models.DetectionSkuReview)
                    .filter(models.DetectionSkuReview.detection_id == regression_detection_id)
                    .order_by(models.DetectionSkuReview.created_at.desc(), models.DetectionSkuReview.id.desc())
                    .first()
                )
                assert latest_regression_review is not None
                db.add(models.Observation(
                    shelf_id=forged_shelf_id,
                    product_id=product_id,
                    source="simulation",
                    status="EMPTY",
                    confidence=0.91,
                    observed_quantity=0,
                    notes=(
                        f"demo_detection_id={regression_detection_id}; "
                        f"shelf_image_id={regression_image_id}; sha256={'b' * 64}; "
                        f"human_review_id={latest_regression_review.id}; provider=mock"
                    ),
                    observed_at=models.utc_now(),
                    model_version="mock-shelf-vision-v1",
                ))
                db.commit()
            finally:
                db.close()
            forged_decisions = client.get(
                f"/api/v1/operational-decisions?store_id={store_id}&shelf_id={forged_shelf_id}"
            )
            decisions = client.get(f"/api/v1/operational-decisions?store_id={store_id}&shelf_id={shelf_id}")
            missing_evidence = client.post(
                "/api/v1/tasks/from-operational-decision?approved=true&demo_evidence_required=true",
                json={"store_id": store_id, "shelf_id": shelf_id, "product_id": other_product_id},
            )
            task_payload = {
                "store_id": store_id,
                "shelf_id": shelf_id,
                "product_id": product_id,
                "priority": "NORMAL",
                "requested_quantity": 8,
                "assigned_user_id": employee_id,
                "notes": "Demo vertical: evidência revista e aprovada.",
            }
            created_task = client.post(
                "/api/v1/tasks/from-operational-decision?approved=true&demo_evidence_required=true",
                json=task_payload,
            )
            duplicate_task = client.post(
                "/api/v1/tasks/from-operational-decision?approved=true&demo_evidence_required=true",
                json=task_payload,
            )

            actor["value"] = SimpleNamespace(
                id=employee_id, role="EMPLOYEE", store_id=store_id, full_name="Demo Employee"
            )
            task_id = created_task.json()["id"]
            started_task = client.patch(
                f"/api/v1/tasks/{task_id}/status",
                json={"status": "IN_PROGRESS"},
            )
            completed_task = client.patch(
                f"/api/v1/tasks/{task_id}/status",
                json={"status": "COMPLETED", "actual_quantity": 8},
            )

            actor["value"] = SimpleNamespace(
                id=reviewer_id, role="SUPERVISOR", store_id=store_id, full_name="Demo Supervisor"
            )
            reconciled = client.post(
                f"/api/v1/tasks/{task_id}/reconcile-inventory",
                json={"reason": "Reposição física concluída no cenário de demonstração."},
            )
            duplicate_reconciliation = client.post(
                f"/api/v1/tasks/{task_id}/reconcile-inventory",
                json={"reason": "Tentativa duplicada de reconciliação."},
            )
            task_events = client.get(f"/api/v1/tasks/{task_id}/events")

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert regression_first.status_code == 200
        assert changed_product.status_code == 409
        assert "different product or status" in changed_product.json()["detail"]
        assert forged_decisions.status_code == 200
        assert forged_decisions.json()["decisions"][0]["evidence"] is None
        assert regression_first.json()["product_id"] == product_id
        assert first.json()["product_id"] == product_id
        assert first.json()["status"] == "EMPTY"
        assert first.json()["observed_quantity"] == 0
        assert f"sha256={'a' * 64}" in first.json()["notes"]
        assert "human_confirmed_status=EMPTY" in first.json()["notes"]
        assert f"human_status_confirmed_by_user_id={reviewer_id}" in first.json()["notes"]
        assert "human_status_confirmed_at=" in first.json()["notes"]
        assert decisions.status_code == 200
        by_product = {row["product_id"]: row for row in decisions.json()["decisions"]}
        assert by_product[product_id]["replenishment_assessment"] is not None
        assert by_product[product_id]["evidence"]["sha256"] == "a" * 64
        assert by_product[other_product_id]["replenishment_assessment"] is None
        assert by_product[other_product_id]["evidence"] is None
        assert missing_evidence.status_code == 409
        assert missing_evidence.json()["detail"]["code"] == "DEMO_EVIDENCE_REQUIRED"
        assert created_task.status_code == 201, created_task.text
        assert created_task.json()["status"] == "ASSIGNED"
        assert created_task.json()["assigned_user_id"] == employee_id
        assert duplicate_task.status_code == 409
        assert duplicate_task.json()["detail"]["code"] == "ACTIVE_TASK_EXISTS"
        assert started_task.status_code == 200, started_task.text
        assert completed_task.status_code == 200, completed_task.text
        assert completed_task.json()["status"] == "COMPLETED"
        assert completed_task.json()["actual_quantity"] == 8
        assert reconciled.status_code == 201, reconciled.text
        assert reconciled.json()["quantity"] == 8
        assert reconciled.json()["result_snapshot_id"] is not None
        assert duplicate_reconciliation.status_code == 409
        assert duplicate_reconciliation.json()["detail"]["code"] == "INVENTORY_ALREADY_RECONCILED"
        assert task_events.status_code == 200
        assert "INVENTORY_RECONCILED" in {event["event_type"] for event in task_events.json()}

        db = TestingSession()
        try:
            assert db.query(models.Observation).filter(
                models.Observation.notes.like(f"%demo_detection_id={detection_id};%")
            ).count() == 1
            assert db.query(models.InventoryMovement).filter_by(task_id=task_id).count() == 1
        finally:
            db.close()
    finally:
        if previous_db_override is not None:
            app.dependency_overrides[get_db] = previous_db_override
        else:
            app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=ENGINE)



def test_store_employee_listing_is_role_and_store_scoped(monkeypatch):
    previous_db_override = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    db = TestingSession()
    try:
        store_a = models.Store(code="DEMO-EMP-A", name="Demo employee A")
        store_b = models.Store(code="DEMO-EMP-B", name="Demo employee B")
        db.add_all([store_a, store_b])
        db.flush()
        supervisor = models.User(
            email="supervisor@demo-employee.test", full_name="Supervisor A",
            password_hash="not-used", role="SUPERVISOR", store_id=store_a.id, is_active=True,
        )
        employee_a = models.User(
            email="employee-a@demo-employee.test", full_name="Employee A",
            password_hash="not-used", role="EMPLOYEE", store_id=store_a.id, is_active=True,
        )
        employee_b = models.User(
            email="employee-b@demo-employee.test", full_name="Employee B",
            password_hash="not-used", role="EMPLOYEE", store_id=store_b.id, is_active=True,
        )
        db.add_all([supervisor, employee_a, employee_b])
        db.commit()
        actor = {"value": SimpleNamespace(id=supervisor.id, role="SUPERVISOR", store_id=store_a.id)}
        store_a_id, store_b_id = store_a.id, store_b.id
        employee_a_id, employee_b_id = employee_a.id, employee_b.id
    finally:
        db.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(main_module, "_request_user", lambda db, request: actor["value"])
    try:
        with TestClient(app) as client:
            scoped = client.get("/api/v1/store-employees")
            assert scoped.status_code == 200
            assert [row["id"] for row in scoped.json()] == [employee_a_id]
            forbidden_store = client.get(f"/api/v1/store-employees?store_id={store_b_id}")
            assert forbidden_store.status_code == 403

            actor["value"] = SimpleNamespace(id=employee_a_id, role="EMPLOYEE", store_id=store_a_id)
            forbidden_role = client.get("/api/v1/store-employees")
            assert forbidden_role.status_code == 403

            actor["value"] = SimpleNamespace(id=999, role="ADMIN", store_id=None)
            admin_list = client.get("/api/v1/store-employees")
            assert admin_list.status_code == 200
            assert {row["id"] for row in admin_list.json()} == {employee_a_id, employee_b_id}
    finally:
        if previous_db_override is not None:
            app.dependency_overrides[get_db] = previous_db_override
        else:
            app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=ENGINE)
