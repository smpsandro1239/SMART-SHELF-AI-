"""Prove PostgreSQL eligibility locks serialize with shelf/zone tenant moves.

The release gate must retain locks on the image, shelf and zone until the
caller commits its release/consumption decision. Two independent PostgreSQL
sessions exercise updates to the shelf and zone while that gate is open.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep
from uuid import uuid4

from sqlalchemy import text

from app import models
from app.database import SessionLocal
from app.dataset_operational_eligibility import validate_internal_image_eligibility


def _create_fixture(suffix: str) -> dict[str, int | str]:
    with SessionLocal() as db:
        store_a = models.Store(
            code=f"PG-DATASET-LOCK-A-{suffix}",
            name="Dataset eligibility lock store A",
        )
        store_b = models.Store(
            code=f"PG-DATASET-LOCK-B-{suffix}",
            name="Dataset eligibility lock store B",
        )
        db.add_all([store_a, store_b])
        db.flush()

        zone_a = models.Zone(store_id=store_a.id, name=f"Dataset lock zone A {suffix}")
        zone_b = models.Zone(store_id=store_b.id, name=f"Dataset lock zone B {suffix}")
        zone_c = models.Zone(store_id=store_a.id, name=f"Dataset lock zone C {suffix}")
        db.add_all([zone_a, zone_b, zone_c])
        db.flush()

        shelf_move = models.Shelf(
            zone_id=zone_a.id,
            code=f"PG-DATASET-SHELF-MOVE-{suffix}",
        )
        shelf_zone = models.Shelf(
            zone_id=zone_c.id,
            code=f"PG-DATASET-ZONE-MOVE-{suffix}",
        )
        db.add_all([shelf_move, shelf_zone])
        db.flush()

        image_shelf = models.ShelfImage(
            shelf_id=shelf_move.id,
            original_filename="dataset-shelf-move.jpg",
            storage_path=f"/tmp/pg-dataset-shelf-move-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=16,
            sha256="a" * 64,
            retention_status="ACTIVE",
            legal_hold=False,
        )
        image_zone = models.ShelfImage(
            shelf_id=shelf_zone.id,
            original_filename="dataset-zone-move.jpg",
            storage_path=f"/tmp/pg-dataset-zone-move-{suffix}.jpg",
            mime_type="image/jpeg",
            file_size_bytes=16,
            sha256="b" * 64,
            retention_status="ACTIVE",
            legal_hold=False,
        )
        db.add_all([image_shelf, image_zone])
        db.commit()

        return {
            "store_a_id": store_a.id,
            "store_b_id": store_b.id,
            "zone_b_id": zone_b.id,
            "zone_c_id": zone_c.id,
            "shelf_move_id": shelf_move.id,
            "zone_move_id": zone_c.id,
            "image_shelf_id": image_shelf.id,
            "image_zone_id": image_zone.id,
            "image_shelf_sha256": image_shelf.sha256,
            "image_zone_sha256": image_zone.sha256,
        }


def _assert_update_waits_for_gate(
    *,
    image_id: int,
    store_id: int,
    image_sha256: str,
    application_name: str,
    update_sql: str,
    update_params: dict[str, int],
) -> None:
    gate_locked = Event()
    release_gate = Event()
    update_started = Event()
    update_finished = Event()

    def eligibility_transaction() -> None:
        with SessionLocal() as db:
            errors, report = validate_internal_image_eligibility(
                db,
                [{
                    "source_type": "internal",
                    "shelf_image_id": image_id,
                    "store_id": store_id,
                    "source_image_sha256": image_sha256,
                }],
            )
            assert errors == [], errors
            assert report["status"] == "APPROVED", report
            assert report["locked_image_ids"] == [image_id], report
            assert len(report["locked_shelf_ids"]) == 1, report
            assert len(report["locked_zone_ids"]) == 1, report
            gate_locked.set()
            if not release_gate.wait(timeout=20):
                raise TimeoutError("dataset eligibility transaction was not released")
            db.commit()

    def hierarchy_update_transaction() -> None:
        with SessionLocal() as db:
            db.execute(
                text("SELECT set_config('application_name', :name, false)"),
                {"name": application_name},
            )
            update_started.set()
            db.execute(text(update_sql), update_params)
            db.commit()
            update_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        gate_future = executor.submit(eligibility_transaction)
        assert gate_locked.wait(timeout=10), (
            "dataset eligibility did not acquire image/shelf/zone locks"
        )
        update_future = executor.submit(hierarchy_update_transaction)
        assert update_started.wait(timeout=10), "hierarchy update did not start"

        deadline = monotonic() + 10
        observed_blocker = False
        try:
            while monotonic() < deadline:
                with SessionLocal() as monitor:
                    activity = monitor.execute(
                        text(
                            "SELECT wait_event_type, pg_blocking_pids(pid) "
                            "FROM pg_stat_activity WHERE application_name = :name"
                        ),
                        {"name": application_name},
                    ).first()

                if activity is not None and activity[0] == "Lock" and activity[1]:
                    observed_blocker = True
                    break
                if update_finished.is_set():
                    break
                sleep(0.05)

            assert observed_blocker, (
                "hierarchy update did not appear as a PostgreSQL lock waiter "
                "blocked by dataset eligibility"
            )
            assert not update_finished.is_set(), (
                "hierarchy update completed before eligibility committed"
            )
        finally:
            release_gate.set()

        gate_future.result(timeout=15)
        update_future.result(timeout=15)

    assert update_finished.is_set(), (
        "hierarchy update did not complete after eligibility released its locks"
    )


def main() -> None:
    suffix = uuid4().hex[:10]
    fixture = _create_fixture(suffix)

    _assert_update_waits_for_gate(
        image_id=int(fixture["image_shelf_id"]),
        store_id=int(fixture["store_a_id"]),
        image_sha256=str(fixture["image_shelf_sha256"]),
        application_name=f"ss-dataset-shelf-{suffix}",
        update_sql="UPDATE shelves SET zone_id = :zone_id WHERE id = :shelf_id",
        update_params={
            "zone_id": int(fixture["zone_b_id"]),
            "shelf_id": int(fixture["shelf_move_id"]),
        },
    )

    _assert_update_waits_for_gate(
        image_id=int(fixture["image_zone_id"]),
        store_id=int(fixture["store_a_id"]),
        image_sha256=str(fixture["image_zone_sha256"]),
        application_name=f"ss-dataset-zone-{suffix}",
        update_sql="UPDATE zones SET store_id = :store_id WHERE id = :zone_id",
        update_params={
            "store_id": int(fixture["store_b_id"]),
            "zone_id": int(fixture["zone_move_id"]),
        },
    )

    with SessionLocal() as db:
        shelf = db.get(models.Shelf, int(fixture["shelf_move_id"]))
        zone = db.get(models.Zone, int(fixture["zone_move_id"]))
        assert shelf is not None and shelf.zone_id == int(fixture["zone_b_id"])
        assert zone is not None and zone.store_id == int(fixture["store_b_id"])

    print(
        "PostgreSQL dataset eligibility concurrency smoke passed: "
        "shelf.zone_id and zone.store_id updates waited for the active "
        "image/shelf/zone eligibility transaction and completed after commit."
    )


if __name__ == "__main__":
    main()
