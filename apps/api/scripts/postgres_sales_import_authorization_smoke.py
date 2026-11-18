"""Verify hourly CSV import tenant isolation on PostgreSQL with real JWT middleware.

The smoke creates two isolated stores, denies cross-store multipart uploads
before parsing, verifies that no foreign rows are persisted, and confirms
that the same supervisor can import valid CSV data into their own store.
"""
from datetime import date
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
    db = SessionLocal()
    try:
        store_a = models.Store(code=f"PG-CSV-A-{suffix}", name="CSV authorization store A")
        store_b = models.Store(code=f"PG-CSV-B-{suffix}", name="CSV authorization store B")
        product = models.Product(sku=f"PG-CSV-SKU-{suffix}", name="CSV authorization product")
        db.add_all([store_a, store_b, product])
        db.flush()
        supervisor = models.User(
            email=f"pg-csv-supervisor-{suffix}@example.test",
            full_name="PostgreSQL CSV authorization supervisor",
            password_hash="smoke-test-only",
            role="SUPERVISOR",
            store_id=store_a.id,
            is_active=True,
        )
        db.add(supervisor)
        db.commit()
        store_a_id, store_b_id = store_a.id, store_b.id
        product_id, supervisor_id = product.id, supervisor.id
    finally:
        db.close()

    original_settings = main_module.settings
    main_module.settings = original_settings.model_copy(update={"app_env": "production"})
    headers = _bearer(supervisor_id, "SUPERVISOR")
    business_date = date.today().isoformat()
    foreign_sales_ref = f"PG-CSV-FOREIGN-SALES-{suffix}"
    foreign_traffic_ref = f"PG-CSV-FOREIGN-TRAFFIC-{suffix}"
    own_sales_ref = f"PG-CSV-OWN-SALES-{suffix}"
    own_traffic_ref = f"PG-CSV-OWN-TRAFFIC-{suffix}"

    sales_header = "product_id,business_date,hour_of_day,quantity,external_reference"
    traffic_header = "business_date,hour_of_day,customer_count,external_reference"
    invalid_sales = (sales_header + "\n" + f"not-an-id,{business_date},10,3,{foreign_sales_ref}" + "\n").encode()
    valid_foreign_traffic = (traffic_header + "\n" + f"{business_date},10,12,{foreign_traffic_ref}" + "\n").encode()
    valid_own_sales = (sales_header + "\n" + f"{product_id},{business_date},10,3,{own_sales_ref}" + "\n").encode()
    valid_own_traffic = (traffic_header + "\n" + f"{business_date},10,12,{own_traffic_ref}" + "\n").encode()

    try:
        with TestClient(app) as client:
            with SessionLocal() as verify:
                daily_before = verify.query(models.DailySalesRecord).filter_by(store_id=store_b_id).count()
                sales_before = verify.query(models.HourlySalesRecord).filter_by(store_id=store_b_id).count()
                traffic_before = verify.query(models.HourlyStoreTrafficRecord).filter_by(store_id=store_b_id).count()

            denied_daily = client.post(
                "/api/v1/sales/import-csv",
                data={"store_id": str(store_b_id), "source": "IMPORT"},
                files={"file": ("foreign-daily.csv", invalid_daily, "text/csv")},
                headers=headers,
            )
            assert denied_daily.status_code == 403, (
                f"Cross-store daily sales CSV must be rejected before parsing: "
                f"{denied_daily.status_code} {denied_daily.text}"
            )

            denied_sales = client.post(
                "/api/v1/sales/hourly/import-csv",
                data={"store_id": str(store_b_id), "source": "IMPORT"},
                files={"file": ("foreign-sales.csv", invalid_sales, "text/csv")},
                headers=headers,
            )
            assert denied_sales.status_code == 403, (
                f"Cross-store sales CSV must be rejected before parsing: "
                f"{denied_sales.status_code} {denied_sales.text}"
            )
            denied_traffic = client.post(
                "/api/v1/sales/traffic/hourly/import-csv",
                data={"store_id": str(store_b_id), "source": "IMPORT"},
                files={"file": ("foreign-traffic.csv", valid_foreign_traffic, "text/csv")},
                headers=headers,
            )
            assert denied_traffic.status_code == 403, (
                f"Cross-store traffic CSV must be rejected: "
                f"{denied_traffic.status_code} {denied_traffic.text}"
            )

            with SessionLocal() as verify:
                daily_after = verify.query(models.DailySalesRecord).filter_by(store_id=store_b_id).count()
                sales_after = verify.query(models.HourlySalesRecord).filter_by(store_id=store_b_id).count()
                traffic_after = verify.query(models.HourlyStoreTrafficRecord).filter_by(store_id=store_b_id).count()
                assert daily_after == daily_before, (daily_before, daily_after)
                assert sales_after == sales_before, (sales_before, sales_after)
                assert traffic_after == traffic_before, (traffic_before, traffic_after)

            own_daily = client.post(
                "/api/v1/sales/import-csv",
                data={"store_id": str(store_a_id), "source": "IMPORT"},
                files={"file": ("own-daily.csv", valid_own_daily, "text/csv")},
                headers=headers,
            )
            assert own_daily.status_code == 200, own_daily.text

            own_sales = client.post(
                "/api/v1/sales/hourly/import-csv",
                data={"store_id": str(store_a_id), "source": "IMPORT"},
                files={"file": ("own-sales.csv", valid_own_sales, "text/csv")},
                headers=headers,
            )
            assert own_sales.status_code == 200, own_sales.text
            own_traffic = client.post(
                "/api/v1/sales/traffic/hourly/import-csv",
                data={"store_id": str(store_a_id), "source": "IMPORT"},
                files={"file": ("own-traffic.csv", valid_own_traffic, "text/csv")},
                headers=headers,
            )
            assert own_traffic.status_code == 200, own_traffic.text

            with SessionLocal() as verify:
                daily_count = verify.query(models.DailySalesRecord).filter_by(
                    store_id=store_a_id, external_reference=own_daily_ref
                ).count()
                sales_count = verify.query(models.HourlySalesRecord).filter_by(
                    store_id=store_a_id, external_reference=own_sales_ref
                ).count()
                traffic_count = verify.query(models.HourlyStoreTrafficRecord).filter_by(
                    store_id=store_a_id, external_reference=own_traffic_ref
                ).count()
                assert daily_count == 1, daily_count
                assert sales_count == 1, sales_count
                assert traffic_count == 1, traffic_count
    finally:
        main_module.settings = original_settings

    print(
        "PostgreSQL CSV authorization smoke passed: daily sales, hourly sales "
        "and hourly traffic cross-store imports returned 403 without writes; "
        "same-store imports persisted exactly one row per endpoint."
    )


if __name__ == "__main__":
    main()
