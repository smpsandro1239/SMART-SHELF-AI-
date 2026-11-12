import os
from datetime import date, timedelta

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

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


def setup_function():
    Base.metadata.drop_all(bind=TEST_ENGINE)
    Base.metadata.create_all(bind=TEST_ENGINE)
    app.dependency_overrides[get_db] = override_get_db


def teardown_function():
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=TEST_ENGINE)


def create_store_and_product(client):
    store = client.post("/api/v1/stores", json={"code": "SALES-01", "name": "Loja vendas"})
    product = client.post("/api/v1/products", json={"sku": "SALES-001", "name": "Leite 1 L"})
    assert store.status_code == 201
    assert product.status_code == 201
    return store.json()["id"], product.json()["id"]


def record_payload(store_id, product_id, sales_date, quantity, reference):
    return {
        "store_id": store_id,
        "product_id": product_id,
        "sales_date": sales_date.isoformat(),
        "quantity": quantity,
        "source": "POS",
        "external_reference": reference,
    }


def test_daily_sales_ingestion_and_demand_forecast():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        today = date.today()
        for offset in range(7):
            day = today - timedelta(days=6 - offset)
            response = client.post(
                "/api/v1/sales/daily",
                json=record_payload(store_id, product_id, day, 5, f"POS-{day.isoformat()}"),
            )
            assert response.status_code == 201

        forecast = client.get("/api/v1/forecasting/demand", params={
            "store_id": store_id,
            "product_id": product_id,
            "source": "POS",
            "lead_time_days": 3,
            "days": 7,
            "through_date": today.isoformat(),
        })
        assert forecast.status_code == 200
        data = forecast.json()
        assert data["forecast"]["status"] == "FORECAST_READY"
        assert data["forecast"]["average_daily_demand"] == 5
        assert data["forecast"]["expected_lead_time_demand"] == 15
        assert "no purchase order" in data["policy"].lower()


def test_forecast_refuses_to_treat_missing_sales_days_as_zero():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        today = date.today()
        for offset in range(6):
            day = today - timedelta(days=6 - offset)
            client.post(
                "/api/v1/sales/daily",
                json=record_payload(store_id, product_id, day, 2, f"POS-{day.isoformat()}"),
            )

        response = client.get("/api/v1/forecasting/demand", params={
            "store_id": store_id,
            "product_id": product_id,
            "source": "POS",
            "lead_time_days": 2,
            "days": 7,
            "through_date": today.isoformat(),
        })
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "INCOMPLETE_DAILY_SALES_HISTORY"
        assert today.isoformat() in response.json()["detail"]["missing_days"]


def test_daily_sales_external_reference_is_idempotency_guard():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        payload = record_payload(store_id, product_id, date.today(), 3, "POS-BATCH-001")
        assert client.post("/api/v1/sales/daily", json=payload).status_code == 201
        duplicate = client.post("/api/v1/sales/daily", json=payload)
        assert duplicate.status_code == 409


def test_daily_sales_rejects_negative_quantity_and_unknown_product():
    with TestClient(app) as client:
        store_id, product_id = create_store_and_product(client)
        negative = client.post("/api/v1/sales/daily", json=record_payload(
            store_id, product_id, date.today(), -1, "POS-NEGATIVE",
        ))
        assert negative.status_code == 422

        unknown = client.post("/api/v1/sales/daily", json=record_payload(
            store_id, 99999, date.today(), 1, "POS-UNKNOWN",
        ))
        assert unknown.status_code == 404
