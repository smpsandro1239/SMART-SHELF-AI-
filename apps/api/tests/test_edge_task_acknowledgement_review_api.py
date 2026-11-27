"""HTTP authorization and idempotency coverage for human Edge ACK reviews."""
import os
from datetime import datetime, timedelta, timezone

os.environ["APP_ENV"]="test"
os.environ["DATABASE_URL"]="sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base, get_db
from app.edge_task_acknowledgement_service import apply_edge_task_acknowledgement
from app.edge_task_assignment_service import create_edge_task_assignment
from app.main import app
import app.main as main_module


ENGINE=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool)
TestingSession=sessionmaker(bind=ENGINE,autoflush=False,autocommit=False)


def override_get_db():
    db=TestingSession()
    try: yield db
    finally: db.close()


@pytest.fixture()
def review_api(monkeypatch):
    previous_override = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    app.dependency_overrides[get_db]=override_get_db
    with TestingSession() as db:
        store=models.Store(code="REVIEW-API-STORE",name="Loja API")
        db.add(store); db.flush()
        actor=models.User(email="review-api-supervisor@example.test",store_id=store.id,
            full_name="Supervisora API",password_hash="test-only",role="SUPERVISOR",is_active=True)
        employee=models.User(email="review-api-employee@example.test",store_id=store.id,
            full_name="Funcionário API",password_hash="test-only",role="EMPLOYEE",is_active=True)
        zone=models.Zone(store_id=store.id,name="Zona")
        product=models.Product(sku="REVIEW-API-SKU",name="Produto",unit="un")
        device=models.EdgeDevice(device_id="review-api-device",store_id=store.id,device_type="robot",status="ACTIVE")
        db.add_all([actor,employee,zone,product,device]); db.flush()
        shelf=models.Shelf(zone_id=zone.id,code="REVIEW-API-SHELF"); db.add(shelf); db.flush()
        task=models.ReplenishmentTask(store_id=store.id,shelf_id=shelf.id,product_id=product.id,status="PENDING")
        db.add(task); db.commit()
        now=datetime.now(timezone.utc)
        create_edge_task_assignment(db,store_id=store.id,task_id=task.id,device_id=device.device_id,
            actor=actor,reason="Teste API",valid_from=now-timedelta(minutes=1),
            valid_until=now+timedelta(hours=1),allowed_actions=["COMPLETED"])
        inbox=models.EdgeDeviceEventInbox(device_id=device.device_id,
            event_id="00000000-0000-4000-8000-000000000105",sequence_number=5,
            event_type="TASK_ACKNOWLEDGED",store_id=store.id,shelf_id=None,occurred_at=now,
            payload={"task_id":task.id,"task_version":task.task_version,"action":"COMPLETED"},
            fingerprint_sha256="d"*64,received_at=now)
        db.add(inbox); db.commit()
        apply_edge_task_acknowledgement(db,{"event_type":"TASK_ACKNOWLEDGED","store_id":store.id,
            "device_id":device.device_id,"inbox_id":inbox.id,"event_id":inbox.event_id,
            "sequence_number":inbox.sequence_number,"fingerprint_sha256":inbox.fingerprint_sha256,
            "occurred_at":now,"payload":inbox.payload})
        db.commit()
        ack_id=db.query(models.EdgeTaskAcknowledgement).one().id
        actor_id=actor.id
    with TestingSession() as read_db:
        actor=read_db.get(models.User,actor_id)
        read_db.expunge(actor)
    monkeypatch.setattr(main_module,"_request_user",lambda db,request: actor)
    yield ack_id,actor
    if previous_override is None:
        app.dependency_overrides.pop(get_db,None)
    else:
        app.dependency_overrides[get_db]=previous_override
    Base.metadata.drop_all(bind=ENGINE)


def test_review_http_post_get_and_idempotent_replay(review_api):
    ack_id,_actor=review_api
    payload={"decision":"APPROVED","reason":"Reposição verificada","evidence_reference":"evidence://shift/123",
             "idempotency_key":"http-review-0001"}
    with TestClient(app) as client:
        created=client.post(f"/api/v1/edge-task-acknowledgements/{ack_id}/reviews",json=payload)
        assert created.status_code==201
        replay=client.post(f"/api/v1/edge-task-acknowledgements/{ack_id}/reviews",json=payload)
        assert replay.status_code==200
        assert replay.json()["id"]==created.json()["id"]
        history=client.get(f"/api/v1/edge-task-acknowledgements/{ack_id}/reviews")
        assert history.status_code==200 and len(history.json())==1


def test_review_http_denies_employee_and_hides_foreign_ack(review_api):
    ack_id,actor=review_api
    actor.role="EMPLOYEE"
    payload={"decision":"REJECTED","reason":"Não foi possível confirmar","evidence_reference":"evidence://shift/124",
             "idempotency_key":"http-review-0002"}
    with TestClient(app) as client:
        denied=client.post(f"/api/v1/edge-task-acknowledgements/{ack_id}/reviews",json=payload)
        assert denied.status_code==403
        actor.role="SUPERVISOR"
        actor.store_id=999999
        foreign=client.get(f"/api/v1/edge-task-acknowledgements/{ack_id}/reviews")
        assert foreign.status_code==404
