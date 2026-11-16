"""Exercise concurrent duplicate CSV imports against PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app


def main() -> None:
    suffix = uuid4().hex[:12]
    db = SessionLocal()
    try:
        store = models.Store(code=f"CSV-RACE-{suffix}", name="PostgreSQL CSV race")
        db.add(store)
        db.flush()
        product = models.Product(sku=f"CSV-RACE-SKU-{suffix}", name="CSV race product")
        supervisor = models.User(
            email=f"csv-race-{suffix}@example.test",
            full_name="CSV race supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store.id,
            is_active=True,
        )
        db.add_all([product, supervisor])
        db.commit()
        store_id, product_id = store.id, product.id\n        actor = type("Actor", (), {"id": supervisor.id, "role": supervisor.role, "store_id": supervisor.store_id})()
    finally:
        db.close()

    original_settings = main_module.settings
    original_request_user = main_module._request_user
    main_module.settings = original_settings.model_copy(update={"app_env": "test"})
    main_module._request_user = lambda db, request: actor
    today = date.today().isoformat()
    cases = (
        ("/api/v1/sales/import-csv",
         "product_id,sales_date,quantity,external_reference",
         f"{product_id},{today},3,DAILY-{suffix}",
         models.DailySalesRecord, f"DAILY-{suffix}"),
        ("/api/v1/sales/hourly/import-csv",
         "product_id,business_date,hour_of_day,quantity,external_reference",
         f"{product_id},{today},10,3,HOURLY-{suffix}",
         models.HourlySalesRecord, f"HOURLY-{suffix}"),
        ("/api/v1/sales/traffic/hourly/import-csv",
         "business_date,hour_of_day,customer_count,external_reference",
         f"{today},10,12,TRAFFIC-{suffix}",
         models.HourlyStoreTrafficRecord, f"TRAFFIC-{suffix}"),
    )

    try:
        with TestClient(app) as client:
            for endpoint, header, row, record_model, reference in cases:
                payload = (header + "\n" + row + "\n").encode("utf-8")
                barrier = Barrier(2)

                def submit():
                    barrier.wait(timeout=10)
                    return client.post(
                        endpoint,
                        data={"store_id": str(store_id), "source": "IMPORT"},
                        files={"file": (f"{reference}.csv", payload, "text/csv")},
                    )

                with ThreadPoolExecutor(max_workers=2) as executor:
                    responses = list(executor.map(lambda _: submit(), range(2)))

                successes = [r for r in responses if r.status_code == 200]
                conflicts = [r for r in responses if r.status_code == 409]
                assert len(successes) == 1, [
                    (r.status_code, r.text) for r in responses
                ]
                assert len(conflicts) == 1, [
                    (r.status_code, r.text) for r in responses
                ]
                assert "no rows were saved" in conflicts[0].text.lower()

                verify_db = SessionLocal()
                try:
                    persisted = (
                        verify_db.query(record_model)
                        .filter(
                            record_model.store_id == store_id,
                            record_model.external_reference == reference,
                        )
                        .count()
                    )
                    assert persisted == 1, (endpoint, reference, persisted)
                finally:
                    verify_db.close()
    finally:
        main_module._request_user = original_request_user
        main_module.settings = original_settings

    print(
        "PostgreSQL concurrent CSV import smoke passed: each of the three "
        "endpoints committed one request, rejected its competitor with 409, "
        "and persisted exactly one row."
    )


if __name__ == "__main__":
    main()
