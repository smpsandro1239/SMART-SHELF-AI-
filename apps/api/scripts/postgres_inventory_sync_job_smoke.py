"""PostgreSQL 16 smoke for durable ERP/WMS job concurrency and crash recovery.

This deliberately exercises real PostgreSQL sessions and process termination.
It does not claim to simulate a provider page commit; snapshot replay remains
covered by the orchestrator's idempotency tests.
"""
from multiprocessing import get_context
from time import sleep
from uuid import uuid4

from sqlalchemy import update

from app import models
from app.database import SessionLocal
from app.inventory_sync_jobs import (
    InventorySyncJobLeaseLost,
    assert_and_renew_inventory_sync_job_lease,
    claim_next_inventory_sync_job,
    enqueue_inventory_sync_job,
)


def _crashing_worker(ready, store_id, user_id, job_id):
    """Claim a job, commit STARTED, then wait to be SIGKILLed by the parent."""
    with SessionLocal() as db:
        job = db.get(models.InventorySyncJob, job_id)
        claim = claim_next_inventory_sync_job(
            db, worker_id="crash-worker", lease_seconds=1
        )
        assert claim is not None and claim.id == job.id
        now = models.utc_now()
        sync = models.InventorySourceSync(
            store_id=store_id,
            source="ERP",
            provider="ERP-PG-Smoke",
            status="STARTED",
            started_at=now,
            created_by_user_id=user_id,
            created_at=now,
        )
        db.add(sync)
        db.flush()
        job.latest_sync_id = sync.id
        db.add(models.InventorySourceSyncEvent(
            sync_id=sync.id,
            event_type="STARTED",
            actor_user_id=user_id,
            details={"source": "ERP", "provider": "ERP-PG-Smoke", "execution": "crash-smoke"},
            created_at=now,
        ))
        db.commit()
        ready.set()
        sleep(60)


def _new_job(suffix):
    with SessionLocal() as db:
        store = models.Store(code=f"PG-INV-SYNC-{suffix}", name="Inventory sync smoke")
        db.add(store)
        db.flush()
        user = models.User(
            email=f"pg-inventory-sync-{suffix}@example.test",
            full_name="Inventory Sync Smoke",
            password_hash="test-only",
            role="ADMIN",
            store_id=None,
            is_active=True,
        )
        db.add(user)
        db.flush()
        db.add(models.StoreExternalIntegration(
            store_id=store.id,
            external_system="ERP",
            provider="ERP-PG-Smoke",
            status="ACTIVE",
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        ))
        db.commit()
        job = enqueue_inventory_sync_job(
            db,
            store_id=store.id,
            source="ERP",
            provider="ERP-PG-Smoke",
            idempotency_key=f"pg-inventory-sync-{suffix}",
            requested_by_user_id=user.id,
        )
        return store.id, user.id, job.id


def _verify_concurrent_single_claim():
    suffix = uuid4().hex[:10]
    store_id, user_id, job_id = _new_job(suffix)
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    barrier = Barrier(2)

    def claim(worker):
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            job = claim_next_inventory_sync_job(db, worker_id=worker, lease_seconds=60)
            return None if job is None else (job.id, job.fencing_token, job.lease_token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("claimant-a", "claimant-b")))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1, f"expected one PostgreSQL claimant, got {results}"
    assert winners[0][0] == job_id
    return job_id, winners[0]


def _verify_stale_worker_fencing():
    suffix = uuid4().hex[:10]
    store_id, user_id, job_id = _new_job(suffix)
    with SessionLocal() as db:
        old = claim_next_inventory_sync_job(db, worker_id="worker-a", lease_seconds=1)
        assert old is not None and old.id == job_id
        db.execute(update(models.InventorySyncJob).where(
            models.InventorySyncJob.id == job_id
        ).values(lease_expires_at=models.utc_now()))
        db.commit()
    sleep(0.05)
    with SessionLocal() as db:
        replacement = claim_next_inventory_sync_job(
            db, worker_id="worker-b", lease_seconds=60
        )
        assert replacement is not None and replacement.fencing_token == old.fencing_token + 1
        try:
            assert_and_renew_inventory_sync_job_lease(
                db, job_id=job_id, worker_id="worker-a",
                lease_token=old.lease_token, fencing_token=old.fencing_token,
            )
        except InventorySyncJobLeaseLost:
            pass
        else:
            raise AssertionError("stale worker renewed a lease after PostgreSQL takeover")


def _verify_sigkill_recovery():
    suffix = uuid4().hex[:10]
    store_id, user_id, job_id = _new_job(suffix)
    context = get_context("fork")
    ready = context.Event()
    process = context.Process(
        target=_crashing_worker, args=(ready, store_id, user_id, job_id)
    )
    process.start()
    try:
        assert ready.wait(timeout=15), "worker did not commit STARTED before timeout"
        sleep(1.1)
        process.kill()
        process.join(timeout=10)
        assert process.exitcode == -9, f"expected SIGKILL exit -9, got {process.exitcode}"
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=10)

    with SessionLocal() as db:
        replacement = claim_next_inventory_sync_job(
            db, worker_id="recovery-worker", lease_seconds=60
        )
        assert replacement is not None and replacement.id == job_id
        sync = db.get(models.InventorySourceSync, replacement.latest_sync_id)
        assert sync is not None
        assert sync.status == "PARTIAL"
        assert sync.error_code == "WORKER_LEASE_EXPIRED"
        assert sync.finished_at is not None
        assert sync.received_records is None and sync.processed_records is None
        events = db.query(models.InventorySourceSyncEvent).filter_by(
            sync_id=sync.id
        ).order_by(models.InventorySourceSyncEvent.id).all()
        assert [event.event_type for event in events] == ["STARTED", "COMPLETED"]
        assert events[-1].details["record_counts_known"] is False


def main():
    _verify_concurrent_single_claim()
    _verify_stale_worker_fencing()
    _verify_sigkill_recovery()
    print(
        "PostgreSQL 16 inventory sync smoke passed: concurrent single claim, "
        "stale-worker fencing and SIGKILL recovery of an abandoned STARTED ledger. "
        "Provider-page replay/idempotency is not exercised by this smoke."
    )


if __name__ == "__main__":
    main()
