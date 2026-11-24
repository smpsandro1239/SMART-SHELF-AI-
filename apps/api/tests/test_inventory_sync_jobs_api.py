"""Authenticated store-scoped API tests for durable inventory sync jobs."""
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app import main as main_module, models
from app.database import Base
from app.schemas import InventorySyncJobEnqueue


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_enqueue_list_and_events_are_store_scoped(db_session):
    store_a = models.Store(code="QUEUE-A", name="Queue A")
    store_b = models.Store(code="QUEUE-B", name="Queue B")
    db_session.add_all([store_a, store_b])
    db_session.flush()
    supervisor = models.User(email="queue-supervisor@example.test", full_name="Supervisor",
        password_hash="test", role="SUPERVISOR", store_id=store_a.id, is_active=True)
    db_session.add(supervisor)
    db_session.flush()
    db_session.add(models.StoreExternalIntegration(store_id=store_a.id, external_system="ERP",
        provider="ERP-Test", status="ACTIVE", created_by_user_id=supervisor.id, updated_by_user_id=supervisor.id))
    db_session.commit()
    request = SimpleNamespace(state=SimpleNamespace(user_id=supervisor.id))
    payload = InventorySyncJobEnqueue(source="ERP", provider="ERP-Test", idempotency_key="api-request-1")
    first = main_module.enqueue_store_inventory_sync_job(store_a.id, payload, request, db_session)
    repeated = main_module.enqueue_store_inventory_sync_job(store_a.id, payload, request, db_session)
    assert first["id"] == repeated["id"] and first["status"] == "QUEUED"
    listed = main_module.list_store_inventory_sync_jobs(store_a.id, request=request, db=db_session)
    assert [item["id"] for item in listed["items"]] == [first["id"]]
    events = main_module.list_store_inventory_sync_job_events(store_a.id, first["id"], request, db_session)
    assert [item["event_type"] for item in events["items"]] == ["QUEUED"]
    with pytest.raises(HTTPException) as foreign:
        main_module.list_store_inventory_sync_job_events(store_b.id, first["id"], request, db_session)
    assert foreign.value.status_code == 403
