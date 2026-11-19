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


def _payload(product_id):
    return {
        "calibration_source": "MANUAL",
        "cells": [{
            "cell_code": "A1", "row_index": 0, "column_index": 0,
            "x_min": 0.0, "y_min": 0.0, "x_max": 0.5, "y_max": 1.0,
            "expected_product_id": product_id,
        }],
    }


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

