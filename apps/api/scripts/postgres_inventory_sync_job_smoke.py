"""PostgreSQL 16 integration smoke for durable ERP/WMS worker safety.

Exercises independent PostgreSQL sessions/processes, a real orchestrator page
commit, SIGKILL between pages, lease takeover and idempotent page replay.
"""
from multiprocessing import get_context
from threading import Event, Thread
from time import monotonic, sleep
from uuid import uuid4
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.exc import DBAPIError

from app import models
from app.database import SessionLocal
from app.inventory_connectors.contracts import InventorySyncBatch, NormalizedInventoryRecord
from app.inventory_connectors.orchestrator import run_inventory_source_sync
from app.inventory_sync_jobs import (
    InventorySyncJobLeaseLost,
    assert_and_renew_inventory_sync_job_lease,
    claim_next_inventory_sync_job,
    complete_inventory_sync_job,
    enqueue_inventory_sync_job,
)

LEASE_SECONDS = 30
PROVIDER = "ERP-PG-Smoke"


def _record(reference, quantity):
    return NormalizedInventoryRecord(
        external_product_id="external-product-1",
        sku="SKU-PG-SMOKE",
        on_hand_quantity=Decimal(quantity),
        reserved_quantity=Decimal("1.000"),
        captured_at=datetime(2026, 11, 25, 10, 0, tzinfo=timezone.utc),
        external_reference=reference,
    )


def _guard(job_id, worker_id, lease_token, fencing_token):
    return lambda session: assert_and_renew_inventory_sync_job_lease(
        session,
        job_id=job_id,
        worker_id=worker_id,
        lease_token=lease_token,
        fencing_token=fencing_token,
        lease_seconds=LEASE_SECONDS,
    )


class _CrashAfterFirstPageAdapter:
    source = "ERP"
    provider = PROVIDER

    def __init__(self, page_committed):
        self.page_committed = page_committed

    async def fetch_inventory(self, store_code, cursor=None):
        if cursor is None:
            return InventorySyncBatch(
                source="ERP", provider=PROVIDER, external_run_id="run-crash-replay",
                records=(_record("external-row-1", "12.000"),), next_cursor="page-2",
            )
        # The orchestrator commits page one before requesting page two.
        self.page_committed.set()
        sleep(60)
        raise AssertionError("parent should SIGKILL this worker before page two returns")


class _ReplayAdapter:
    source = "ERP"
    provider = PROVIDER

    async def fetch_inventory(self, store_code, cursor=None):
        if cursor is None:
            return InventorySyncBatch(
                source="ERP", provider=PROVIDER, external_run_id="run-crash-replay",
                records=(_record("external-row-1", "12.000"),), next_cursor="page-2",
            )
        return InventorySyncBatch(
            source="ERP", provider=PROVIDER, external_run_id="run-crash-replay",
            records=(_record("external-row-2", "8.000"),), next_cursor=None,
        )


def _crashing_orchestrator_worker(page_committed, store_id, actor_id, job_id):
    worker_id = "page-crash-worker"
    with SessionLocal() as db:
        claim = claim_next_inventory_sync_job(
            db, worker_id=worker_id, lease_seconds=LEASE_SECONDS
        )
        assert claim is not None and claim.id == job_id
        job_id, lease_token, fencing_token = claim.id, claim.lease_token, claim.fencing_token

    async def execute():
        with SessionLocal() as db:
            return await run_inventory_source_sync(
                db,
                store_id=store_id,
                source="ERP",
                adapter=_CrashAfterFirstPageAdapter(page_committed),
                actor_user_id=actor_id,
                lease_guard=_guard(job_id, worker_id, lease_token, fencing_token),
            )

    import asyncio
    asyncio.run(execute())


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
        product = models.Product(
            sku=f"SKU-PG-{suffix}", name="PostgreSQL inventory smoke product",
            unit="un", is_active=True,
        )
        db.add_all([user, product])
        db.flush()
        db.add(models.StoreExternalIntegration(
            store_id=store.id,
            external_system="ERP",
            provider=PROVIDER,
            status="ACTIVE",
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        ))
        db.add(models.InventoryExternalProductMapping(
            store_id=store.id,
            source="ERP",
            external_product_id="external-product-1",
            external_sku="SKU-PG-SMOKE",
            product_id=product.id,
            active=True,
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
        ))
        db.commit()
        job = enqueue_inventory_sync_job(
            db,
            store_id=store.id,
            source="ERP",
            provider=PROVIDER,
            idempotency_key=f"pg-inventory-sync-{suffix}",
            requested_by_user_id=user.id,
        )
        return store.id, user.id, product.id, job.id



def _verify_store_identity_immutable_under_concurrency():
    """A concurrent tenant reassignment waits for the row lock, then fails closed."""
    suffix = uuid4().hex[:10]
    store_id, _, _, job_id = _new_job(suffix)
    with SessionLocal() as setup:
        foreign_store = models.Store(
            code=f"PG-INV-SYNC-OTHER-{suffix}",
            name="Other inventory sync store",
        )
        setup.add(foreign_store)
        setup.commit()
        foreign_store_id = foreign_store.id

    writer = SessionLocal()
    writer_pid = writer.execute(text("SELECT pg_backend_pid()")).scalar_one()
    job = writer.query(models.InventorySyncJob).filter_by(id=job_id).with_for_update().one()
    assert job.store_id == store_id

    started = Event()
    finished = Event()
    failures = []
    contender_pids = []

    def reassign():
        contender = SessionLocal()
        try:
            contender_pids.append(
                contender.execute(text("SELECT pg_backend_pid()")).scalar_one()
            )
            started.set()
            contender.execute(
                update(models.InventorySyncJob)
                .where(models.InventorySyncJob.id == job_id)
                .values(store_id=foreign_store_id)
            )
            contender.commit()
        except BaseException as exc:
            contender.rollback()
            failures.append(exc)
        finally:
            contender.close()
            finished.set()

    thread = Thread(target=reassign, daemon=True)
    thread.start()
    assert started.wait(timeout=5), "store reassignment contender did not start"
    assert contender_pids, "store reassignment backend PID was not captured"

    observer = SessionLocal()
    deadline = monotonic() + 5
    observed_blocker = False
    try:
        while monotonic() < deadline and not finished.is_set():
            row = observer.execute(
                text("""
                    SELECT wait_event_type, pg_blocking_pids(pid) AS blocking_pids
                    FROM pg_stat_activity WHERE pid = :pid
                """),
                {"pid": contender_pids[0]},
            ).one_or_none()
            if (
                row is not None
                and row.wait_event_type == "Lock"
                and writer_pid in (row.blocking_pids or [])
            ):
                observed_blocker = True
                break
            sleep(0.01)
    finally:
        observer.close()

    assert observed_blocker, (
        "store reassignment did not wait on the locked inventory sync job row; "
        f"writer={writer_pid}, contender={contender_pids[0]}"
    )
    assert not finished.is_set(), "store reassignment completed before row lock release"
    writer.commit()
    writer.close()
    thread.join(timeout=10)
    assert finished.is_set(), "store reassignment remained blocked after row lock release"
    assert len(failures) == 1, f"expected immutable-tenant rejection, got {failures!r}"
    assert "inventory sync job store_id is immutable" in str(failures[0]), (
        f"store reassignment failed for an unexpected reason: {failures[0]!r}"
    )

    with SessionLocal() as verify:
        persisted = verify.get(models.InventorySyncJob, job_id)
        assert persisted is not None and persisted.store_id == store_id
        # The guard is column-specific: ordinary worker lifecycle updates remain valid.
        persisted.status = "CANCELLED"
        persisted.finished_at = models.utc_now()
        persisted.updated_at = models.utc_now()
        verify.commit()
        verify.refresh(persisted)
        assert persisted.status == "CANCELLED"


def _verify_concurrent_single_claim():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    suffix = uuid4().hex[:10]
    _, _, _, job_id = _new_job(suffix)
    barrier = Barrier(2)

    def claim(worker):
        with SessionLocal() as db:
            barrier.wait(timeout=10)
            job = claim_next_inventory_sync_job(db, worker_id=worker, lease_seconds=LEASE_SECONDS)
            return None if job is None else (job.id, job.fencing_token, job.lease_token)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("claimant-a", "claimant-b")))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1, f"expected one PostgreSQL claimant, got {results}"
    assert winners[0][0] == job_id


def _verify_stale_worker_fencing():
    suffix = uuid4().hex[:10]
    store_id, actor_id, product_id, job_id = _new_job(suffix)
    with SessionLocal() as db:
        old = claim_next_inventory_sync_job(db, worker_id="worker-a", lease_seconds=LEASE_SECONDS)
        assert old is not None and old.id == job_id
        # Capture lease credentials while the ORM instance is attached. The
        # claim commits internally; the session expires ORM attributes on
        # commit, and the instance becomes detached when this context closes.
        old_lease_token = old.lease_token
        old_fencing_token = old.fencing_token
        db.execute(update(models.InventorySyncJob).where(
            models.InventorySyncJob.id == job_id
        ).values(lease_expires_at=models.utc_now()))
        db.commit()
    with SessionLocal() as db:
        replacement = claim_next_inventory_sync_job(
            db, worker_id="worker-b", lease_seconds=LEASE_SECONDS
        )
        assert replacement is not None
        replacement_fencing_token = replacement.fencing_token
        assert replacement_fencing_token == old_fencing_token + 1
        try:
            assert_and_renew_inventory_sync_job_lease(
                db, job_id=job_id, worker_id="worker-a",
                lease_token=old_lease_token, fencing_token=old_fencing_token,
                lease_seconds=LEASE_SECONDS,
            )
        except InventorySyncJobLeaseLost:
            pass
        else:
            raise AssertionError("stale worker renewed a lease after PostgreSQL takeover")

    # Exercise the actual orchestrator write path with worker A's stale fencing
    # credentials. The lease guard must reject it before a sync ledger or page
    # snapshot can be committed.
    async def stale_page_attempt():
        with SessionLocal() as db:
            return await run_inventory_source_sync(
                db,
                store_id=store_id,
                source="ERP",
                adapter=_ReplayAdapter(),
                actor_user_id=actor_id,
                lease_guard=_guard(
                    job_id, "worker-a", old_lease_token, old_fencing_token
                ),
            )

    import asyncio
    try:
        asyncio.run(stale_page_attempt())
    except InventorySyncJobLeaseLost:
        pass
    else:
        raise AssertionError("stale worker orchestrator unexpectedly accepted a page")
    with SessionLocal() as db:
        snapshot_count = db.query(models.InventorySnapshot).filter_by(
            store_id=store_id, product_id=product_id, source="ERP"
        ).count()
        sync_count = db.query(models.InventorySourceSync).filter_by(
            store_id=store_id, source="ERP"
        ).count()
        assert snapshot_count == 0, "stale worker persisted an inventory snapshot"
        assert sync_count == 0, "stale worker created a source-sync ledger"


def _verify_sigkill_after_page_commit_and_idempotent_replay():
    suffix = uuid4().hex[:10]
    store_id, actor_id, product_id, job_id = _new_job(suffix)
    context = get_context("spawn")
    page_committed = context.Event()
    process = context.Process(
        target=_crashing_orchestrator_worker,
        args=(page_committed, store_id, actor_id, job_id),
    )
    process.start()
    try:
        assert page_committed.wait(timeout=30), "worker did not reach page-two fetch after page-one commit"
        with SessionLocal() as db:
            first_page = db.query(models.InventorySnapshot).filter_by(
                store_id=store_id, product_id=product_id, source="ERP",
                external_reference="external-row-1",
            ).one_or_none()
            assert first_page is not None, "page one was not committed before SIGKILL"
            initial_sync = db.query(models.InventorySourceSync).filter_by(
                store_id=store_id, source="ERP", status="STARTED"
            ).order_by(models.InventorySourceSync.id.desc()).first()
            assert initial_sync is not None, "source-sync ledger was not created"
            assert first_page.source_sync_id == initial_sync.id
            initial_sync_id = initial_sync.id
            first_snapshot_id = first_page.id
            first_snapshot_quantity = Decimal(str(first_page.on_hand_quantity))
        process.kill()
        process.join(timeout=15)
        assert process.exitcode == -9, f"expected SIGKILL exit -9, got {process.exitcode}"
    finally:
        if process.is_alive():
            process.kill()
            process.join(timeout=15)

    with SessionLocal() as db:
        db.execute(update(models.InventorySyncJob).where(
            models.InventorySyncJob.id == job_id
        ).values(lease_expires_at=models.utc_now()))
        db.commit()
        replacement = claim_next_inventory_sync_job(
            db, worker_id="recovery-worker", lease_seconds=LEASE_SECONDS
        )
        assert replacement is not None and replacement.id == job_id
        abandoned = db.get(models.InventorySourceSync, replacement.latest_sync_id)
        assert abandoned is not None and abandoned.status == "PARTIAL"
        assert abandoned.error_code == "WORKER_LEASE_EXPIRED"
        assert abandoned.finished_at is not None
        assert abandoned.received_records is None and abandoned.processed_records is None
        events = db.query(models.InventorySourceSyncEvent).filter_by(
            sync_id=abandoned.id
        ).order_by(models.InventorySourceSyncEvent.id).all()
        assert [event.event_type for event in events] == ["STARTED", "COMPLETED"]
        assert events[-1].details["record_counts_known"] is False
        replacement_token = replacement.lease_token
        replacement_fencing = replacement.fencing_token

    async def replay():
        with SessionLocal() as db:
            return await run_inventory_source_sync(
                db,
                store_id=store_id,
                source="ERP",
                adapter=_ReplayAdapter(),
                actor_user_id=actor_id,
                lease_guard=_guard(
                    job_id, "recovery-worker", replacement_token, replacement_fencing
                ),
            )

    import asyncio
    result = asyncio.run(replay())
    assert result["status"] == "SUCCESS"
    with SessionLocal() as db:
        snapshots = db.query(models.InventorySnapshot).filter_by(
            store_id=store_id, product_id=product_id, source="ERP"
        ).order_by(models.InventorySnapshot.external_reference).all()
        assert len(snapshots) == 2, f"expected exactly two unique snapshots, got {len(snapshots)}"
        replayed = next(row for row in snapshots if row.external_reference == "external-row-1")
        assert replayed.id == first_snapshot_id, "replay inserted a duplicate snapshot"
        assert replayed.source_sync_id == initial_sync_id, "replay must preserve the original partial-run lineage"
        assert Decimal(str(replayed.on_hand_quantity)) == first_snapshot_quantity
        assert Decimal(str(replayed.on_hand_quantity)) == Decimal("12.000")
        assert {row.external_reference for row in snapshots} == {
            "external-row-1", "external-row-2"
        }
        sync = db.query(models.InventorySourceSync).filter_by(
            store_id=store_id, source="ERP"
        ).order_by(models.InventorySourceSync.id.desc()).first()
        assert sync is not None and sync.status == "SUCCESS"
        replayed_second_page = next(row for row in snapshots if row.external_reference == "external-row-2")
        assert replayed_second_page.source_sync_id == sync.id
        db.add(models.InventorySnapshot(
            store_id=store_id,
            product_id=product_id,
            on_hand_quantity=Decimal("1.000"),
            reserved_quantity=Decimal("0.000"),
            source="ERP",
            external_reference=f"late-terminal-sync-{suffix}",
            source_sync_id=sync.id,
            captured_at=datetime.now(timezone.utc),
            created_at=models.utc_now(),
        ))
        try:
            db.flush()
        except DBAPIError as exc:
            db.rollback()
            if "inventory snapshot source_sync_id provenance mismatch" not in str(exc):
                raise
        else:
            raise AssertionError("terminal sync accepted a new linked inventory snapshot")
        complete_inventory_sync_job(
            db, job_id=job_id, worker_id="recovery-worker",
            lease_token=replacement_token, fencing_token=replacement_fencing,
            status="SUCCEEDED", sync_id=sync.id,
        )


def main():
    _verify_store_identity_immutable_under_concurrency()
    _verify_concurrent_single_claim()
    _verify_stale_worker_fencing()
    _verify_sigkill_after_page_commit_and_idempotent_replay()
    print(
        "PostgreSQL 16 inventory sync smoke passed: immutable store identity under "
        "concurrent reassignment, concurrent single claim, "
        "stale-worker fencing, SIGKILL after a committed page, PARTIAL ledger "
        "recovery and idempotent snapshot replay."
    )


if __name__ == "__main__":
    main()
