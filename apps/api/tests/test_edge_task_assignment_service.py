"""Transactional service tests for Edge device/task assignments."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.edge_task_assignment_service import (
    EdgeTaskAssignmentError,
    create_edge_task_assignment,
    revoke_edge_task_assignment,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = session_factory()
    store = models.Store(code="EDGE-ASSIGN-1", name="Loja de teste")
    db.add(store)
    db.flush()
    user = models.User(
        email="supervisor@example.test", store_id=store.id, full_name="Supervisora",
        password_hash="not-a-real-password-hash", role="SUPERVISOR", is_active=True,
    )
    zone = models.Zone(store_id=store.id, name="Bebidas")
    db.add_all([user, zone])
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="A-01")
    product = models.Product(sku="SKU-EDGE-1", name="Água", unit="un")
    db.add_all([shelf, product])
    db.flush()
    task = models.ReplenishmentTask(
        store_id=store.id, shelf_id=shelf.id, product_id=product.id,
        status="PENDING", priority="NORMAL",
    )
    device = models.EdgeDevice(
        device_id="edge-camera-1", store_id=store.id,
        device_type="fixed_camera", status="ACTIVE",
    )
    db.add_all([task, device])
    db.commit()
    yield db, store, user, task, device
    db.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_create_and_revoke_assignment_are_audited_atomically(db_session):
    db, store, actor, task, device = db_session
    start = datetime.now(timezone.utc)
    assignment = create_edge_task_assignment(
        db, store_id=store.id, task_id=task.id, device_id=device.device_id,
        actor=actor, reason="Inspecção e reposição assistida",
        valid_from=start, valid_until=start + timedelta(hours=2),
    )
    assert assignment.task_version == task.task_version
    created = db.query(models.EdgeDeviceTaskAssignmentEvent).filter_by(
        assignment_id=assignment.id, event_type="CREATED"
    ).one()
    assert created.actor_user_id == actor.id
    assert created.reason == "Inspecção e reposição assistida"

    revoked = revoke_edge_task_assignment(
        db, assignment_id=assignment.id, actor=actor, reason="Equipamento substituído"
    )
    assert revoked.revoked_at is not None
    assert revoked.revoked_by_user_id == actor.id
    assert db.query(models.EdgeDeviceTaskAssignmentEvent).filter_by(
        assignment_id=assignment.id
    ).count() == 2


def test_duplicate_active_assignment_is_rejected(db_session):
    db, store, actor, task, device = db_session
    start = datetime.now(timezone.utc)
    kwargs = dict(
        store_id=store.id, task_id=task.id, device_id=device.device_id, actor=actor,
        reason="Atribuição operacional", valid_from=start,
    )
    create_edge_task_assignment(db, **kwargs)
    with pytest.raises(EdgeTaskAssignmentError) as error:
        create_edge_task_assignment(db, **kwargs)
    assert error.value.status_code == 409
    assert error.value.code == "ACTIVE_ASSIGNMENT_EXISTS"


def test_invalid_actor_and_naive_datetimes_are_rejected(db_session):
    db, store, actor, task, device = db_session
    employee = models.User(
        email="employee@example.test", store_id=store.id, full_name="Funcionário",
        password_hash="not-a-real-password-hash", role="EMPLOYEE", is_active=True,
    )
    db.add(employee)
    db.commit()
    with pytest.raises(EdgeTaskAssignmentError) as denied:
        create_edge_task_assignment(
            db, store_id=store.id, task_id=task.id, device_id=device.device_id,
            actor=employee, reason="Atribuição válida",
            valid_from=datetime.now(timezone.utc),
        )
    assert denied.value.status_code == 403

    with pytest.raises(EdgeTaskAssignmentError) as naive:
        create_edge_task_assignment(
            db, store_id=store.id, task_id=task.id, device_id=device.device_id,
            actor=actor, reason="Atribuição válida",
            valid_from=datetime.now(),
        )
    assert naive.value.code == "TIMEZONE_REQUIRED"


def test_cross_store_device_cannot_be_assigned_to_task(db_session):
    db, store, actor, task, device = db_session
    foreign_store = models.Store(code="EDGE-ASSIGN-2", name="Outra loja")
    db.add(foreign_store)
    db.flush()
    foreign_device = models.EdgeDevice(
        device_id="edge-camera-foreign", store_id=foreign_store.id,
        device_type="fixed_camera", status="ACTIVE",
    )
    db.add(foreign_device)
    db.commit()
    with pytest.raises(EdgeTaskAssignmentError) as error:
        create_edge_task_assignment(
            db, store_id=store.id, task_id=task.id, device_id=foreign_device.device_id,
            actor=actor, reason="Tentativa de associação",
            valid_from=datetime.now(timezone.utc),
        )
    assert error.value.status_code == 404
    assert db.query(models.EdgeDeviceTaskAssignment).count() == 0
