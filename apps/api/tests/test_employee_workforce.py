from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app import models
from app.database import Base
from app.schemas import EmployeeAvailabilityCreate, EmployeeShiftCreate, EmployeeSkillCreate


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def workforce(db):
    store = models.Store(code="WORKFORCE-1", name="Workforce test")
    db.add(store)
    db.flush()
    admin = models.User(
        email="workforce-admin@example.test", full_name="Admin",
        password_hash="test", role="ADMIN", is_active=True,
    )
    employee = models.User(
        email="workforce-employee@example.test", full_name="Employee",
        password_hash="test", role="EMPLOYEE", store_id=store.id, is_active=True,
    )
    db.add_all([admin, employee])
    db.commit()
    return store.id, admin.id, employee.id


def request_for(user_id):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


def test_shift_persists_capacity_and_rejects_overlapping_shift(db_session):
    store_id, admin_id, employee_id = workforce(db_session)
    start = datetime(2026, 12, 1, 8, tzinfo=timezone.utc)
    payload = EmployeeShiftCreate(
        store_id=store_id, employee_id=employee_id,
        starts_at=start, ends_at=start + timedelta(hours=8), break_minutes=30,
    )
    created = main_module.create_employee_shift(payload, request_for(admin_id), db_session)
    assert created.status == "SCHEDULED"
    assert created.break_minutes == 30
    assert (created.ends_at - created.starts_at).total_seconds() // 60 - created.break_minutes == 450

    overlapping = EmployeeShiftCreate(
        store_id=store_id, employee_id=employee_id,
        starts_at=start + timedelta(hours=7), ends_at=start + timedelta(hours=9),
    )
    with pytest.raises(HTTPException) as exc:
        main_module.create_employee_shift(overlapping, request_for(admin_id), db_session)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "SHIFT_OVERLAP"


def test_skill_is_normalized_and_duplicate_is_rejected(db_session):
    store_id, admin_id, employee_id = workforce(db_session)
    payload = EmployeeSkillCreate(
        store_id=store_id, employee_id=employee_id, skill_code="stock_rotation", level=4,
    )
    created = main_module.create_employee_skill(payload, request_for(admin_id), db_session)
    assert created.skill_code == "STOCK_ROTATION"
    assert created.level == 4

    with pytest.raises(HTTPException) as exc:
        main_module.create_employee_skill(payload, request_for(admin_id), db_session)
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "EMPLOYEE_SKILL_EXISTS"


def test_availability_intervals_are_persisted_and_cannot_overlap(db_session):
    store_id, admin_id, employee_id = workforce(db_session)
    start = datetime(2026, 12, 2, 0, tzinfo=timezone.utc)
    payload = EmployeeAvailabilityCreate(
        store_id=store_id, employee_id=employee_id,
        starts_at=start, ends_at=start + timedelta(hours=4),
        status="UNAVAILABLE", reason="Personal leave",
    )
    record = main_module.create_employee_availability(
        payload, request_for(admin_id), db_session,
    )
    assert record.status == "UNAVAILABLE"

    conflict = EmployeeAvailabilityCreate(
        store_id=store_id, employee_id=employee_id,
        starts_at=start + timedelta(hours=3), ends_at=start + timedelta(hours=5),
        status="AVAILABLE",
    )
    with pytest.raises(HTTPException) as exc:
        main_module.create_employee_availability(
            conflict, request_for(admin_id), db_session,
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "AVAILABILITY_OVERLAP"


def test_workforce_records_cannot_be_created_for_an_employee_in_another_store(db_session):
    store_id, admin_id, _ = workforce(db_session)
    other_store = models.Store(code="WORKFORCE-2", name="Other store")
    db_session.add(other_store)
    foreign_employee = models.User(
        email="foreign-employee@example.test", full_name="Foreign",
        password_hash="test", role="EMPLOYEE", store_id=other_store.id, is_active=True,
    )
    db_session.add(foreign_employee)
    db_session.commit()

    payload = EmployeeShiftCreate(
        store_id=store_id, employee_id=foreign_employee.id,
        starts_at=datetime(2026, 12, 3, 8, tzinfo=timezone.utc),
        ends_at=datetime(2026, 12, 3, 16, tzinfo=timezone.utc),
    )
    with pytest.raises(HTTPException) as exc:
        main_module.create_employee_shift(payload, request_for(admin_id), db_session)
    assert exc.value.status_code == 404


def test_supervisor_is_limited_to_own_store(db_session):
    store_id, _, employee_id = workforce(db_session)
    supervisor = models.User(
        email="workforce-supervisor@example.test", full_name="Supervisor",
        password_hash="test", role="SUPERVISOR", store_id=store_id, is_active=True,
    )
    other_store = models.Store(code="WORKFORCE-3", name="Third store")
    db_session.add_all([supervisor, other_store])
    db_session.commit()

    payload = EmployeeSkillCreate(
        store_id=other_store.id, employee_id=employee_id, skill_code="CASHIER",
    )
    with pytest.raises(HTTPException) as exc:
        main_module.create_employee_skill(payload, request_for(supervisor.id), db_session)
    assert exc.value.status_code == 403


def test_workforce_schema_rejects_invalid_time_ranges_and_skill_levels():
    start = datetime(2026, 12, 4, 8, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        EmployeeShiftCreate(
            store_id=1, employee_id=1, starts_at=start,
            ends_at=start, break_minutes=0,
        )
    with pytest.raises(ValueError):
        EmployeeAvailabilityCreate(
            store_id=1, employee_id=1, starts_at=start,
            ends_at=start - timedelta(minutes=1), status="AVAILABLE",
        )
    with pytest.raises(ValueError):
        EmployeeSkillCreate(
            store_id=1, employee_id=1, skill_code="CASHIER", level=6,
        )
