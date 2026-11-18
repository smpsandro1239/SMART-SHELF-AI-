"""Exercise stale vision-job recovery and lease fencing on real PostgreSQL.

The first phase holds one stale image row lock while a recovery worker scans
with SKIP LOCKED. It must recover another row without waiting, then recover
the held row after its lock is released. The second phase replaces a worker's
claim while inference is running and proves that the old successful result
cannot overwrite the replacement lease or persist detections.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from app import models
from app.database import SessionLocal
from app.vision import DetectionResult, VisionAnalysis
from app.vision_worker import process_next_image, requeue_stale_processing_images
from app.config import settings


def _create_fixture(suffix: str) -> tuple[int, list[int]]:
    with SessionLocal() as db:
        store = models.Store(
            code=f"PG-VISION-RECOVERY-{suffix}",
            name="PostgreSQL vision recovery smoke",
        )
        db.add(store)
        db.flush()
        zone = models.Zone(store_id=store.id, name="Vision recovery zone")
        db.add(zone)
        db.flush()
        shelf = models.Shelf(zone_id=zone.id, code=f"PG-VISION-{suffix}")
        db.add(shelf)
        db.flush()

        stale_at = models.utc_now() - timedelta(hours=1)
        stale_images = [
            models.ShelfImage(
                shelf_id=shelf.id,
                original_filename=f"stale-{index}.jpg",
                storage_path=f"/tmp/pg-vision-stale-{suffix}-{index}.jpg",
                mime_type="image/jpeg",
                file_size_bytes=10,
                sha256=f"{index + 1:x}" * 64,
                analysis_status="PROCESSING",
                analysis_started_at=stale_at,
                retention_status="ACTIVE",
            )
            for index in range(2)
        ]
        pending_image = models.ShelfImage(
            shelf_id=shelf.id,
            original_filename="lease-fencing.jpg",
            storage_path=f"/tmp/pg-vision-pending-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=10,
            sha256="c" * 64,
            analysis_status="PENDING",
            retention_status="ACTIVE",
        )
        db.add_all([*stale_images, pending_image])
        db.commit()
        return store.id, [image.id for image in stale_images] + [pending_image.id]


def _verify_skip_locked_recovery(stale_image_ids: list[int]) -> None:
    held_image_id, available_image_id = stale_image_ids[:2]
    with SessionLocal() as lock_holder:
        lock_holder.query(models.ShelfImage).filter(
            models.ShelfImage.id == held_image_id
        ).with_for_update().one()

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_recover_stale_images)
            recovered_while_locked = future.result(timeout=10)

        assert recovered_while_locked == 1, (
            "recovery must skip the locked row and recover the other stale image"
        )
        held = lock_holder.get(models.ShelfImage, held_image_id)
        assert held is not None and held.analysis_status == "PROCESSING"

    with SessionLocal() as db:
        available = db.get(models.ShelfImage, available_image_id)
        assert available is not None
        assert available.analysis_status == "PENDING"
        recovered_after_release = requeue_stale_processing_images(
            db, stale_after_seconds=60
        )
        assert recovered_after_release == 1

    with SessionLocal() as db:
        states = {
            image.id: image.analysis_status
            for image in db.query(models.ShelfImage)
            .filter(models.ShelfImage.id.in_(stale_image_ids[:2]))
            .all()
        }
        assert states == {
            held_image_id: "PENDING",
            available_image_id: "PENDING",
        }, states


def _recover_stale_images() -> int:
    with SessionLocal() as db:
        return requeue_stale_processing_images(db, stale_after_seconds=60)


def _verify_successful_stale_lease_is_fenced(
    store_id: int,
    pending_image_id: int,
    suffix: str,
) -> None:
    from app import vision_worker

    with TemporaryDirectory(prefix=f"ss-vision-{suffix}-") as directory:
        root = Path(directory)
        store_root = root / str(store_id)
        store_root.mkdir(parents=True)
        image_path = store_root / "lease-fencing.jpg"
        image_path.write_bytes(b"vision-worker-postgresql-smoke")

        previous_storage_path = settings.image_storage_path
        settings.image_storage_path = str(root)
        replacement_lease = models.utc_now() + timedelta(minutes=5)

        class TakingOverProvider:
            def analyze(self, _path: Path) -> VisionAnalysis:
                with SessionLocal() as takeover_db:
                    image = takeover_db.get(models.ShelfImage, pending_image_id)
                    assert image is not None
                    image.analysis_status = "PROCESSING"
                    image.analysis_started_at = replacement_lease
                    image.analysis_error = None
                    image.analysis_completed_at = None
                    takeover_db.commit()

                return VisionAnalysis(
                    model_version="pg-vision-lease-fencing-v1",
                    detections=[
                        DetectionResult(
                            label="product",
                            confidence=0.95,
                            x_min=0.1,
                            y_min=0.1,
                            x_max=0.8,
                            y_max=0.9,
                        )
                    ],
                )

        try:
            with SessionLocal() as db:
                processed_id = process_next_image(db, TakingOverProvider())
                assert processed_id == pending_image_id
        finally:
            settings.image_storage_path = previous_storage_path

    with SessionLocal() as db:
        image = db.get(models.ShelfImage, pending_image_id)
        assert image is not None
        assert image.analysis_status == "PROCESSING"
        assert image.analysis_started_at == replacement_lease
        assert image.analysis_completed_at is None
        assert image.model_version is None
        assert db.query(models.ShelfImageDetection).filter(
            models.ShelfImageDetection.shelf_image_id == pending_image_id
        ).count() == 0


def main() -> None:
    suffix = uuid4().hex[:10]
    store_id, image_ids = _create_fixture(suffix)
    _verify_skip_locked_recovery(image_ids)
    _verify_successful_stale_lease_is_fenced(store_id, image_ids[2], suffix)
    print(
        "PostgreSQL vision recovery smoke passed: SKIP LOCKED recovery "
        "processed available stale rows without waiting for a competing "
        "row lock, recovered the remaining row after release, and fenced "
        "a successful inference result after lease takeover."
    )


if __name__ == "__main__":
    main()
