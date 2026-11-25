"""Independent polling worker for durable ERP/WMS synchronization jobs."""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import socket
import time
from app.config import settings
from app.database import SessionLocal
from app.inventory_connectors.contracts import load_inventory_adapter
from app.inventory_connectors.orchestrator import run_inventory_source_sync
from app.inventory_sync_jobs import (
    InventorySyncJobLeaseLost, assert_and_renew_inventory_sync_job_lease,
    claim_next_inventory_sync_job, complete_inventory_sync_job,
    fail_or_retry_inventory_sync_job,
)

logger = logging.getLogger("smart_shelf.inventory_sync_worker")


def process_next_job(worker_id: str, lease_seconds: int = 300) -> bool:
    with SessionLocal() as db:
        job = claim_next_inventory_sync_job(db, worker_id=worker_id, lease_seconds=lease_seconds)
        if job is None:
            return False
        job_id, store_id, source = job.id, job.store_id, job.source
        actor_id, lease_token, fencing_token = job.requested_by_user_id, job.lease_token, job.fencing_token
    try:
        factory_path = (
            settings.inventory_erp_adapter_factory if source == "ERP"
            else settings.inventory_wms_adapter_factory
        ).strip()
        adapter = load_inventory_adapter(factory_path, expected_source=source)

        async def execute():
            with SessionLocal() as db:
                guard = lambda session: assert_and_renew_inventory_sync_job_lease(
                    session, job_id=job_id, worker_id=worker_id,
                    lease_token=lease_token, fencing_token=fencing_token,
                    lease_seconds=lease_seconds,
                )
                return await run_inventory_source_sync(
                    db, store_id=store_id, source=source, adapter=adapter,
                    actor_user_id=actor_id, lease_guard=guard,
                )

        result = asyncio.run(execute())
        with SessionLocal() as db:
            complete_inventory_sync_job(
                db, job_id=job_id, worker_id=worker_id, lease_token=lease_token,
                fencing_token=fencing_token, status="SUCCEEDED", sync_id=int(result["sync_id"]),
            )
        logger.info("Inventory sync job %s completed", job_id)
    except InventorySyncJobLeaseLost:
        logger.warning("Inventory sync job %s lost its lease; stale worker stopped", job_id)
    except Exception as exc:
        # Provider exception text is deliberately not logged or persisted.
        code = "ADAPTER_NOT_CONFIGURED" if type(exc).__name__ == "InventoryAdapterNotConfigured" else "SYNC_EXECUTION_FAILED"
        try:
            with SessionLocal() as db:
                failed = fail_or_retry_inventory_sync_job(
                    db, job_id=job_id, worker_id=worker_id, lease_token=lease_token,
                    fencing_token=fencing_token, error_code=code,
                )
            logger.error("Inventory sync job %s failed; state=%s", job_id, failed.status)
        except InventorySyncJobLeaseLost:
            logger.warning("Inventory sync job %s failed after losing its lease; stale update rejected", job_id)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Durable ERP/WMS inventory synchronization worker")
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--lease-seconds", type=int, default=300)
    parser.add_argument("--worker-id", default=os.getenv("INVENTORY_SYNC_WORKER_ID", f"{socket.gethostname()}-{os.getpid()}"))
    args = parser.parse_args()
    if not 0.5 <= args.poll_interval <= 300:
        parser.error("--poll-interval must be between 0.5 and 300 seconds")
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    logger.info("Inventory sync worker started")
    while True:
        try:
            if not process_next_job(args.worker_id, args.lease_seconds):
                time.sleep(args.poll_interval)
        except KeyboardInterrupt:
            logger.info("Inventory sync worker stopping")
            break
        except Exception as exc:
            logger.error("Inventory sync worker loop recovered from %s", type(exc).__name__)
            time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
