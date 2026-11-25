"""Durable ERP/WMS queue, retry and fencing regression tests."""
from datetime import timedelta, timezone
import pytest
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import sessionmaker
from app import models
from app.database import Base
from app.inventory_sync_jobs import (
    InventorySyncJobConflict, InventorySyncJobLeaseLost,
    assert_and_renew_inventory_sync_job_lease, claim_next_inventory_sync_job,
    complete_inventory_sync_job, enqueue_inventory_sync_job,
    fail_or_retry_inventory_sync_job,
)


@pytest.fixture
def db(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'inventory-sync-jobs.db'}")
    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = factory()
    store = models.Store(code="SYNC-JOB-STORE", name="Sync Job Store")
    session.add(store)
    session.flush()
    user = models.User(email="sync-job@example.test", full_name="Sync Operator",
        password_hash="test", role="ADMIN", store_id=None, is_active=True)
    session.add(user)
    session.flush()
    session.add(models.StoreExternalIntegration(store_id=store.id, external_system="ERP",
        provider="ERP-Test", status="ACTIVE", created_by_user_id=user.id, updated_by_user_id=user.id))
    session.commit()
    session.info["store_id"], session.info["user_id"] = store.id, user.id
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def enqueue(db, key="request-1"):
    return enqueue_inventory_sync_job(db, store_id=db.info["store_id"], source="ERP",
        provider="ERP-Test", idempotency_key=key, requested_by_user_id=db.info["user_id"])


def test_enqueue_is_idempotent_and_audited(db):
    first, second = enqueue(db), enqueue(db)
    assert first.id == second.id and first.status == "QUEUED"
    events = db.query(models.InventorySyncJobEvent).filter_by(job_id=first.id).all()
    assert [(e.sequence_number, e.event_type) for e in events] == [(1, "QUEUED")]


def test_idempotency_key_cannot_be_reused_for_another_provider(db):
    enqueue(db)
    with pytest.raises(InventorySyncJobConflict):
        enqueue_inventory_sync_job(db, store_id=db.info["store_id"], source="ERP",
            provider="Other-ERP", idempotency_key="request-1", requested_by_user_id=db.info["user_id"])


def test_claim_and_completion_use_fencing_and_random_lease_token(db):
    job = enqueue(db)
    claim = claim_next_inventory_sync_job(db, worker_id="worker-a", lease_seconds=30)
    assert claim.id == job.id and claim.status == "RUNNING"
    assert claim.fencing_token == 1 and claim.attempt_count == 1 and claim.lease_token
    done = complete_inventory_sync_job(db, job_id=job.id, worker_id="worker-a",
        lease_token=claim.lease_token, fencing_token=claim.fencing_token, status="SUCCEEDED")
    assert done.status == "SUCCEEDED" and done.lease_token is None


def test_expired_lease_takeover_fences_out_old_worker(db):
    job = enqueue(db)
    old = claim_next_inventory_sync_job(db, worker_id="worker-old", lease_seconds=30)
    old_lease_token = old.lease_token
    old_fencing_token = old.fencing_token
    db.execute(update(models.InventorySyncJob).where(models.InventorySyncJob.id == job.id)
        .values(lease_expires_at=models.utc_now() - timedelta(seconds=1)))
    db.commit()
    new = claim_next_inventory_sync_job(db, worker_id="worker-new", lease_seconds=30)
    assert new.fencing_token == old_fencing_token + 1 and new.lease_token != old_lease_token
    with pytest.raises(InventorySyncJobLeaseLost):
        assert_and_renew_inventory_sync_job_lease(db, job_id=job.id, worker_id="worker-old",
            lease_token=old_lease_token, fencing_token=old_fencing_token)
    done = complete_inventory_sync_job(db, job_id=job.id, worker_id="worker-new",
        lease_token=new.lease_token, fencing_token=new.fencing_token, status="SUCCEEDED")
    assert done.status == "SUCCEEDED"


def test_expired_lease_closes_abandoned_source_sync_before_takeover(db):
    job = enqueue(db)
    old = claim_next_inventory_sync_job(db, worker_id="worker-crashed", lease_seconds=30)
    old_lease_token = old.lease_token
    old_fencing_token = old.fencing_token
    now = models.utc_now()
    sync = models.InventorySourceSync(
        store_id=job.store_id,
        source="ERP",
        provider="ERP-Test",
        status="STARTED",
        started_at=now,
        created_by_user_id=db.info["user_id"],
        created_at=now,
    )
    db.add(sync)
    db.flush()
    job.latest_sync_id = sync.id
    job.lease_expires_at = now - timedelta(seconds=1)
    db.commit()

    replacement = claim_next_inventory_sync_job(db, worker_id="worker-recovery", lease_seconds=30)

    db.refresh(sync)
    assert replacement.fencing_token == old_fencing_token + 1
    assert sync.status == "PARTIAL"
    assert sync.finished_at is not None
    assert sync.error_code == "WORKER_LEASE_EXPIRED"
    assert sync.received_records is None and sync.processed_records is None
    events = db.query(models.InventorySourceSyncEvent).filter_by(sync_id=sync.id).all()
    assert [(event.event_type, event.details["error_code"]) for event in events] == [
        ("COMPLETED", "WORKER_LEASE_EXPIRED")
    ]
    with pytest.raises(InventorySyncJobLeaseLost):
        assert_and_renew_inventory_sync_job_lease(
            db, job_id=job.id, worker_id="worker-crashed",
            lease_token=old_lease_token, fencing_token=old_fencing_token,
        )


def test_failure_schedules_retry_then_terminal_failure(db):
    job = enqueue(db)
    first = claim_next_inventory_sync_job(db, worker_id="worker-a", lease_seconds=30)
    retry = fail_or_retry_inventory_sync_job(db, job_id=job.id, worker_id="worker-a",
        lease_token=first.lease_token, fencing_token=first.fencing_token, error_code="PROVIDER_TIMEOUT")
    scheduled = retry.scheduled_at
    if scheduled.tzinfo is None:
        scheduled = scheduled.replace(tzinfo=timezone.utc)
    assert retry.status == "QUEUED" and scheduled > models.utc_now()
    retry.scheduled_at = models.utc_now() - timedelta(seconds=1)
    db.commit()
    second = claim_next_inventory_sync_job(db, worker_id="worker-b", lease_seconds=30)
    assert second.attempt_count == 2
    second.scheduled_at = models.utc_now() - timedelta(seconds=1)
    second.lease_expires_at = models.utc_now() - timedelta(seconds=1)
    db.commit()
    third = claim_next_inventory_sync_job(db, worker_id="worker-c", lease_seconds=30)
    assert third.attempt_count == 3
    final = fail_or_retry_inventory_sync_job(db, job_id=job.id, worker_id="worker-c",
        lease_token=third.lease_token, fencing_token=third.fencing_token, error_code="PROVIDER_TIMEOUT")
    assert final.status == "FAILED" and final.finished_at is not None


def test_scheduled_job_is_not_claimed_early(db):
    job = enqueue(db)
    job.scheduled_at = models.utc_now() + timedelta(hours=1)
    db.commit()
    assert claim_next_inventory_sync_job(db, worker_id="worker-a") is None
