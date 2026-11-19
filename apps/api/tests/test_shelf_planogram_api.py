import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_shelf_planogram_api_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module, models
from app.database import Base, get_db
from app.security import create_access_token, hash_password


@pytest.fixture
def planogram_api(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    with session_factory() as db:
        store_a = models.Store(code="PLANO-A", name="Planogram Store A")
        store_b = models.Store(code="PLANO-B", name="Planogram Store B")
        db.add_all([store_a, store_b])
        db.flush()
        zone_a = models.Zone(store_id=store_a.id, name="A")
        zone_b = models.Zone(store_id=store_b.id, name="B")
        db.add_all([zone_a, zone_b])
        db.flush()
        shelf_a = models.Shelf(zone_id=zone_a.id, code="A-01")
        shelf_b = models.Shelf(zone_id=zone_b.id, code="B-01")
        db.add_all([shelf_a, shelf_b])
        users = {
            "admin": models.User(email="planogram-admin@test.invalid", full_name="Admin", password_hash=hash_password("test-password"), role="ADMIN", is_active=True),
            "supervisor_a": models.User(email="planogram-supervisor-a@test.invalid", full_name="Supervisor A", password_hash=hash_password("test-password"), role="SUPERVISOR", store_id=store_a.id, is_active=True),
            "supervisor_b": models.User(email="planogram-supervisor-b@test.invalid", full_name="Supervisor B", password_hash=hash_password("test-password"), role="SUPERVISOR", store_id=store_b.id, is_active=True),
            "employee_a": models.User(email="planogram-employee@test.invalid", full_name="Employee", password_hash=hash_password("test-password"), role="EMPLOYEE", store_id=store_a.id, is_active=True),
        }
        db.add_all(users.values())
        product_a = models.Product(sku="PLANO-SKU-A", name="Product A", is_active=True)
        product_b = models.Product(sku="PLANO-SKU-B", name="Product B", is_active=True)
        db.add_all([product_a, product_b])
        db.flush()
        db.add_all([
            models.ShelfProduct(shelf_id=shelf_a.id, product_id=product_a.id, target_quantity=10, min_display_quantity=2),
            models.ShelfProduct(shelf_id=shelf_b.id, product_id=product_b.id, target_quantity=10, min_display_quantity=2),
        ])
        db.flush()
        ids = {
            "store_a": store_a.id, "store_b": store_b.id,
            "shelf_a": shelf_a.id, "shelf_b": shelf_b.id,
            "product_a": product_a.id, "product_b": product_b.id,
            **{key: value.id for key, value in users.items()},
        }
        db.commit()

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    previous_override = main_module.app.dependency_overrides.get(get_db)
    original_settings = main_module.settings
    main_module.app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(main_module, "SessionLocal", session_factory)
    monkeypatch.setattr(main_module, "settings", original_settings.model_copy(update={"app_env": "production"}))
    try:
        with TestClient(main_module.app) as client:
            yield client, ids
    finally:
        main_module.settings = original_settings
        if previous_override is None:
            main_module.app.dependency_overrides.pop(get_db, None)
        else:
            main_module.app.dependency_overrides[get_db] = previous_override
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _headers(user_id, role):
    token, _ = create_access_token(user_id=user_id, role=role)
    return {"Authorization": f"Bearer {token}"}


def _payload(product_id, expected_facings=None):
    cell = {
        "cell_code": "A1", "row_index": 0, "column_index": 0,
        "x_min": 0.0, "y_min": 0.0, "x_max": 0.5, "y_max": 1.0,
        "expected_product_id": product_id,
    }
    if expected_facings is not None:
        cell["expected_facings"] = expected_facings
    return {"calibration_source": "MANUAL", "cells": [cell]}


def test_supervisor_can_version_activate_and_retire_planograms(planogram_api):
    client, ids = planogram_api
    headers = _headers(ids["supervisor_a"], "SUPERVISOR")
    created = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        json=_payload(ids["product_a"]), headers=headers,
    )
    assert created.status_code == 201, created.text
    first = created.json()
    assert first["version"] == 1 and first["status"] == "DRAFT"
    assert first["cells"][0]["expected_product_id"] == ids["product_a"]

    history = client.get(f"/api/v1/shelves/{ids['shelf_a']}/planograms", headers=headers)
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [first["id"]]
    assert client.get(f"/api/v1/shelves/{ids['shelf_a']}/planograms/active", headers=headers).json() is None

    activated = client.post(
        f"/api/v1/planograms/{first['id']}/activate",
        json={"reason": "Initial shelf calibration approved"}, headers=headers,
    )
    assert activated.status_code == 200, activated.text
    assert activated.json()["status"] == "ACTIVE"

    second = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        json=_payload(ids["product_a"]), headers=headers,
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]
    replaced = client.post(
        f"/api/v1/planograms/{second_id}/activate",
        json={"reason": "Updated facing layout"}, headers=headers,
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["status"] == "ACTIVE"

    history = client.get(f"/api/v1/shelves/{ids['shelf_a']}/planograms", headers=headers)
    assert {item["status"] for item in history.json()} == {"ACTIVE", "RETIRED"}
    retired = client.post(
        f"/api/v1/planograms/{second_id}/retire",
        json={"reason": "Shelf layout withdrawn"}, headers=headers,
    )
    assert retired.status_code == 200, retired.text
    assert retired.json()["status"] == "RETIRED"
    assert client.get(f"/api/v1/shelves/{ids['shelf_a']}/planograms/active", headers=headers).json() is None


def test_planogram_api_enforces_role_and_store_isolation(planogram_api):
    client, ids = planogram_api
    own = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        headers=_headers(ids["supervisor_a"], "SUPERVISOR"),
    )
    foreign = client.get(
        f"/api/v1/shelves/{ids['shelf_b']}/planograms",
        headers=_headers(ids["supervisor_a"], "SUPERVISOR"),
    )
    employee = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        headers=_headers(ids["employee_a"], "EMPLOYEE"),
    )
    missing = client.get(f"/api/v1/shelves/{ids['shelf_a']}/planograms")
    assert own.status_code == 200
    assert foreign.status_code == 403
    assert employee.status_code == 403
    assert missing.status_code == 401


def test_planogram_api_rejects_overlapping_cells_and_unassigned_sku(planogram_api):
    client, ids = planogram_api
    headers = _headers(ids["supervisor_a"], "SUPERVISOR")
    overlap = _payload(ids["product_a"])
    overlap["cells"].append({
        "cell_code": "A2", "row_index": 0, "column_index": 1,
        "x_min": 0.4, "y_min": 0.0, "x_max": 0.8, "y_max": 1.0,
        "expected_product_id": ids["product_a"],
    })
    invalid_geometry = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms", json=overlap, headers=headers,
    )
    wrong_sku = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        json=_payload(ids["product_b"]), headers=headers,
    )
    assert invalid_geometry.status_code == 422
    assert wrong_sku.status_code == 422




def test_draft_planogram_cells_can_be_replaced_and_expected_facings_round_trip(planogram_api):
    client, ids = planogram_api
    headers = _headers(ids["supervisor_a"], "SUPERVISOR")
    created = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        json=_payload(ids["product_a"], expected_facings=2), headers=headers,
    )
    assert created.status_code == 201, created.text
    planogram_id = created.json()["id"]
    assert created.json()["cells"][0]["expected_facings"] == 2

    replacement = {
        "cells": [{
            "cell_code": "B1", "row_index": 0, "column_index": 0,
            "x_min": 0.5, "y_min": 0.0, "x_max": 1.0, "y_max": 1.0,
            "expected_product_id": ids["product_a"], "expected_facings": 4,
        }],
    }
    updated = client.put(
        f"/api/v1/planograms/{planogram_id}/cells",
        json=replacement, headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert [(cell["cell_code"], cell["expected_facings"]) for cell in updated.json()["cells"]] == [("B1", 4)]

    activated = client.post(
        f"/api/v1/planograms/{planogram_id}/activate",
        json={"reason": "Reviewed facing count"}, headers=headers,
    )
    assert activated.status_code == 200, activated.text
    denied = client.put(
        f"/api/v1/planograms/{planogram_id}/cells",
        json=replacement, headers=headers,
    )
    assert denied.status_code == 409


def test_active_planogram_comparison_returns_front_facing_counts_and_provenance(planogram_api):
    client, ids = planogram_api
    headers = _headers(ids["supervisor_a"], "SUPERVISOR")
    created = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        json=_payload(ids["product_a"], expected_facings=2),
        headers=headers,
    )
    assert created.status_code == 201, created.text
    planogram_id = created.json()["id"]
    activated = client.post(
        f"/api/v1/planograms/{planogram_id}/activate",
        json={"reason": "Approved comparison fixture"},
        headers=headers,
    )
    assert activated.status_code == 200, activated.text

    with main_module.SessionLocal() as db:
        image = models.ShelfImage(
            shelf_id=ids["shelf_a"],
            original_filename="comparison.jpg",
            storage_path=f"/tmp/planogram-comparison-{ids['shelf_a']}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=128,
            sha256="a" * 64,
            analysis_status="COMPLETED",
            model_version="detector-test-v1",
            retention_status="ACTIVE",
        )
        db.add(image)
        db.flush()
        detection = models.ShelfImageDetection(
            shelf_image_id=image.id,
            product_id=ids["product_a"],
            label="product",
            confidence=0.97,
            x_min=0.05,
            y_min=0.10,
            x_max=0.22,
            y_max=0.90,
            model_version="detector-test-v1",
            sku_match_status="MATCHED",
        )
        db.add(detection)
        db.commit()
        image_id = image.id
        detection_id = detection.id

    response = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms/comparison/{image_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["shelf_image_id"] == image_id
    assert payload["image_sha256"] == "a" * 64
    assert payload["model_version"] == "detector-test-v1"
    assert payload["planogram_id"] == planogram_id
    assert payload["planogram_version"] == 1
    assert payload["cells"] == [{
        "cell_code": "A1",
        "status": "UNDER_FACED",
        "expected_product_id": ids["product_a"],
        "expected_facings": 2,
        "observed_facings": 1,
        "observed_product_ids": [ids["product_a"]],
        "detection_ids": [detection_id],
        "overlap_ratio": 0.272,
    }]


def test_planogram_comparison_never_infers_empty_without_visibility_calibration(planogram_api):
    client, ids = planogram_api
    headers = _headers(ids["supervisor_a"], "SUPERVISOR")
    created = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        json=_payload(ids["product_a"]),
        headers=headers,
    )
    planogram_id = created.json()["id"]
    activated = client.post(
        f"/api/v1/planograms/{planogram_id}/activate",
        json={"reason": "Approved empty-state fixture"},
        headers=headers,
    )
    assert activated.status_code == 200, activated.text

    with main_module.SessionLocal() as db:
        image = models.ShelfImage(
            shelf_id=ids["shelf_a"],
            original_filename="empty-facing.jpg",
            storage_path=f"/tmp/planogram-empty-{ids['shelf_a']}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=128,
            sha256="b" * 64,
            analysis_status="COMPLETED",
            model_version="detector-test-v1",
            retention_status="ACTIVE",
        )
        db.add(image)
        db.flush()
        db.add(models.ShelfImageDetection(
            shelf_image_id=image.id,
            product_id=None,
            label="empty_facing",
            confidence=0.99,
            x_min=0.05,
            y_min=0.10,
            x_max=0.45,
            y_max=0.90,
            model_version="detector-test-v1",
            sku_match_status="UNKNOWN",
        ))
        db.commit()
        image_id = image.id

    response = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms/comparison/{image_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    cell = response.json()["cells"][0]
    assert cell["status"] == "UNKNOWN"
    assert cell["observed_facings"] == 0


def test_planogram_comparison_enforces_role_store_and_image_state(planogram_api):
    client, ids = planogram_api
    supervisor_a = _headers(ids["supervisor_a"], "SUPERVISOR")
    created = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        json=_payload(ids["product_a"]),
        headers=supervisor_a,
    )
    planogram_id = created.json()["id"]
    client.post(
        f"/api/v1/planograms/{planogram_id}/activate",
        json={"reason": "Comparison authorization fixture"},
        headers=supervisor_a,
    )

    with main_module.SessionLocal() as db:
        image = models.ShelfImage(
            shelf_id=ids["shelf_a"],
            original_filename="pending.jpg",
            storage_path=f"/tmp/planogram-pending-{ids['shelf_a']}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=128,
            sha256="c" * 64,
            analysis_status="PENDING",
            retention_status="ACTIVE",
        )
        db.add(image)
        db.commit()
        image_id = image.id

    own_pending = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms/comparison/{image_id}",
        headers=supervisor_a,
    )
    foreign = client.get(
        f"/api/v1/shelves/{ids['shelf_b']}/planograms/comparison/{image_id}",
        headers=supervisor_a,
    )
    employee = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms/comparison/{image_id}",
        headers=_headers(ids["employee_a"], "EMPLOYEE"),
    )
    assert own_pending.status_code == 409
    assert foreign.status_code == 403
    assert employee.status_code == 403


def test_planogram_comparison_requires_an_active_planogram(planogram_api):
    client, ids = planogram_api
    headers = _headers(ids["supervisor_a"], "SUPERVISOR")
    with main_module.SessionLocal() as db:
        image = models.ShelfImage(
            shelf_id=ids["shelf_a"],
            original_filename="without-planogram.jpg",
            storage_path=f"/tmp/planogram-no-active-{ids['shelf_a']}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=128,
            sha256="d" * 64,
            analysis_status="COMPLETED",
            model_version="detector-test-v1",
            retention_status="ACTIVE",
        )
        db.add(image)
        db.commit()
        image_id = image.id

    response = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms/comparison/{image_id}",
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Shelf has no active planogram"


def test_planogram_comparison_returns_image_calibration_provenance(planogram_api):
    client, ids = planogram_api
    headers = _headers(ids["supervisor_a"], "SUPERVISOR")
    calibration_sha256 = "e" * 64

    with main_module.SessionLocal() as db:
        calibration = models.ShelfImage(
            shelf_id=ids["shelf_a"],
            original_filename="calibration.jpg",
            storage_path=f"/tmp/planogram-calibration-{ids['shelf_a']}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=128,
            sha256=calibration_sha256,
            analysis_status="COMPLETED",
            model_version="calibration-model-v1",
            retention_status="ACTIVE",
        )
        db.add(calibration)
        db.commit()
        calibration_image_id = calibration.id

    payload = _payload(ids["product_a"], expected_facings=2)
    payload.update({
        "calibration_source": "IMAGE",
        "calibration_image_id": calibration_image_id,
        "calibration_image_sha256": calibration_sha256,
    })
    created = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        json=payload,
        headers=headers,
    )
    assert created.status_code == 201, created.text
    planogram_id = created.json()["id"]
    activated = client.post(
        f"/api/v1/planograms/{planogram_id}/activate",
        json={"reason": "Approved image calibration fixture"},
        headers=headers,
    )
    assert activated.status_code == 200, activated.text

    response = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms/comparison/{calibration_image_id}",
        headers=headers,
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["calibration_source"] == "IMAGE"
    assert result["calibration_image_id"] == calibration_image_id
    assert result["calibration_image_sha256"] == calibration_sha256
    assert result["comparison_schema_version"] == 1
    assert len(result["comparison_sha256"]) == 64

    repeated = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms/comparison/{calibration_image_id}",
        headers=headers,
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["comparison_sha256"] == result["comparison_sha256"]


@pytest.mark.parametrize("retention_status", ["RESTRICTED", "PENDING_PURGE", "PURGED"])
def test_planogram_comparison_rejects_unavailable_retained_images(planogram_api, retention_status):
    client, ids = planogram_api
    headers = _headers(ids["supervisor_a"], "SUPERVISOR")
    created = client.post(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms",
        json=_payload(ids["product_a"]),
        headers=headers,
    )
    assert created.status_code == 201, created.text
    planogram_id = created.json()["id"]
    activated = client.post(
        f"/api/v1/planograms/{planogram_id}/activate",
        json={"reason": "Retention guard fixture"},
        headers=headers,
    )
    assert activated.status_code == 200, activated.text

    with main_module.SessionLocal() as db:
        image = models.ShelfImage(
            shelf_id=ids["shelf_a"],
            original_filename=f"unavailable-{retention_status.lower()}.jpg",
            storage_path=f"/tmp/planogram-{retention_status.lower()}-{ids['shelf_a']}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=128,
            sha256="f" * 64,
            analysis_status="COMPLETED",
            model_version="detector-test-v1",
            retention_status=retention_status,
        )
        db.add(image)
        db.commit()
        image_id = image.id

    response = client.get(
        f"/api/v1/shelves/{ids['shelf_a']}/planograms/comparison/{image_id}",
        headers=headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Shelf image is not available"


def test_comparison_fingerprint_is_canonical_and_binds_schema_and_cell_results():
    from app.shelf_planogram_comparison import comparison_fingerprint

    snapshot = {
        "comparison_schema_version": 1,
        "shelf_id": 17,
        "cells": [{"cell_code": "A1", "status": "UNKNOWN"}],
    }
    reordered = {
        "cells": [{"status": "UNKNOWN", "cell_code": "A1"}],
        "shelf_id": 17,
        "comparison_schema_version": 1,
    }
    changed = {
        **snapshot,
        "cells": [{"cell_code": "A1", "status": "OCCUPIED"}],
    }

    assert comparison_fingerprint(snapshot) == comparison_fingerprint(reordered)
    assert comparison_fingerprint(snapshot) != comparison_fingerprint(changed)
    assert comparison_fingerprint({
        **snapshot,
        "comparison_sha256": "0" * 64,
    }) == comparison_fingerprint(snapshot)

    with pytest.raises(ValueError, match="Unsupported comparison schema version"):
        comparison_fingerprint({**snapshot, "comparison_schema_version": 2})
    with pytest.raises(ValueError):
        comparison_fingerprint({**snapshot, "non_finite": float("nan")})
