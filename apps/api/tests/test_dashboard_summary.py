import os
from types import SimpleNamespace

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_dashboard_summary.db"

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app import main as main_module
from app import models


ENGINE = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def isolated_database():
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    yield
    Base.metadata.drop_all(bind=ENGINE)


def seed_dashboard_data():
    db = Session()
    store_a = models.Store(code="DASH-A", name="Dashboard Store A")
    store_b = models.Store(code="DASH-B", name="Dashboard Store B")
    db.add_all([store_a, store_b])
    db.flush()

    zone_a = models.Zone(store_id=store_a.id, name="A")
    zone_b = models.Zone(store_id=store_b.id, name="B")
    db.add_all([zone_a, zone_b])
    db.flush()

    shelf_a1 = models.Shelf(zone_id=zone_a.id, code="A-01")
    shelf_a2 = models.Shelf(zone_id=zone_a.id, code="A-02")
    shelf_b = models.Shelf(zone_id=zone_b.id, code="B-01")
    db.add_all([shelf_a1, shelf_a2, shelf_b])
    db.flush()

    supervisor = models.User(
        email="supervisor-dashboard@example.test",
        full_name="Dashboard Supervisor",
        password_hash="not-used",
        role="SUPERVISOR",
        store_id=store_a.id,
        is_active=True,
    )
    employee = models.User(
        email="employee-dashboard@example.test",
        full_name="Dashboard Employee",
        password_hash="not-used",
        role="EMPLOYEE",
        store_id=store_a.id,
        is_active=True,
    )
    admin = models.User(
        email="admin-dashboard@example.test",
        full_name="Dashboard Admin",
        password_hash="not-used",
        role="ADMIN",
        store_id=None,
        is_active=True,
    )
    db.add_all([supervisor, employee, admin])
    db.flush()

    product = models.Product(sku="DASH-SKU", name="Dashboard product", is_active=True)
    second_product = models.Product(sku="DASH-SKU-2", name="Second dashboard product", is_active=True)
    db.add_all([product, second_product])
    db.flush()

    db.add_all([
        models.ReplenishmentTask(
            store_id=store_a.id, shelf_id=shelf_a1.id, product_id=product.id,
            priority="URGENT", status="PENDING",
        ),
        models.ReplenishmentTask(
            store_id=store_a.id, shelf_id=shelf_a1.id, product_id=second_product.id,
            priority="HIGH", status="ASSIGNED", assigned_user_id=employee.id,
            assigned_to=employee.full_name,
        ),
        models.ReplenishmentTask(
            store_id=store_a.id, shelf_id=shelf_a2.id, product_id=product.id,
            priority="NORMAL", status="COMPLETED", assigned_user_id=employee.id,
        ),
        models.ReplenishmentTask(
            store_id=store_a.id, shelf_id=shelf_a2.id, product_id=product.id,
            priority="LOW", status="CANCELLED",
        ),
        models.ReplenishmentTask(
            store_id=store_b.id, shelf_id=shelf_b.id, product_id=product.id,
            priority="URGENT", status="PENDING",
        ),
    ])

    db.add_all([
        models.Observation(shelf_id=shelf_a1.id, status="LOW_STOCK", source="manual"),
        models.Observation(shelf_id=shelf_a1.id, status="LOW_STOCK", source="manual"),
        models.Observation(shelf_id=shelf_a2.id, status="EMPTY", source="manual"),
        models.Observation(shelf_id=shelf_b.id, status="EMPTY", source="manual"),
    ])
    db.commit()
    result = {
        "store_a": store_a.id,
        "store_b": store_b.id,
        "supervisor": supervisor.id,
        "employee": employee.id,
        "admin": admin.id,
    }
    db.close()
    return result


def call_dashboard(db, user_id, store_id=None):
    request = SimpleNamespace(state=SimpleNamespace(user_id=user_id))
    return main_module.dashboard_summary(request=request, store_id=store_id, db=db)


def test_dashboard_reports_actionable_kpis_and_counts_distinct_shelves():
    ids = seed_dashboard_data()
    with Session() as db:
        summary = call_dashboard(db, ids["supervisor"])

    assert summary["store_id"] == ids["store_a"]
    assert summary["tasks"] == {
        "pending": 1,
        "assigned": 1,
        "in_progress": 0,
        "completed": 1,
        "cancelled": 1,
    }
    assert summary["tasks_by_priority"] == {
        "low": 1,
        "normal": 1,
        "high": 1,
        "urgent": 1,
    }
    assert summary["active_tasks"] == 2
    assert summary["urgent_active_tasks"] == 1
    assert summary["unassigned_active_tasks"] == 1
    assert summary["completion_rate_percent"] == 25.0
    assert summary["attention_observations"] == 3
    assert summary["shelves_requiring_attention"] == 2


def test_dashboard_preserves_employee_and_admin_visibility_boundaries():
    ids = seed_dashboard_data()
    with Session() as db:
        employee_summary = call_dashboard(db, ids["employee"])
        admin_summary = call_dashboard(db, ids["admin"])

    assert employee_summary["role"] == "EMPLOYEE"
    assert employee_summary["tasks"]["assigned"] == 1
    assert employee_summary["tasks"]["completed"] == 1
    assert employee_summary["tasks"]["pending"] == 0
    assert employee_summary["active_tasks"] == 1
    assert employee_summary["unassigned_active_tasks"] == 0
    assert employee_summary["shelves_requiring_attention"] == 2

    assert admin_summary["role"] == "ADMIN"
    assert admin_summary["store_id"] is None
    assert admin_summary["tasks"]["pending"] == 2
    assert admin_summary["observations"]["empty"] == 2
    assert admin_summary["shelves_requiring_attention"] == 3
