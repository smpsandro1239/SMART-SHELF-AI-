"""PostgreSQL concurrency and database-guard smoke for ONNX model anti-rollback."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models import VisionModelReleaseEvent, VisionModelReleaseState
from app.vision_model_release import (
    ModelReleaseError,
    assert_model_release_current,
    register_model_release,
)


def _release(version: int) -> dict:
    return {
        "model_id": "shelf-detector",
        "release_version": version,
        "key_id": "release-smoke",
        "manifest_sha256": f"{version:064x}",
        "detector_sha256": "a" * 64,
        "embedding_sha256": None,
    }


def main() -> None:
    deployment_id = f"ci-model-release-{uuid4().hex}"
    register_model_release(
        SessionLocal,
        deployment_id=deployment_id,
        model_release=_release(1),
    )

    barrier = Barrier(2)

    def advance(version: int) -> str:
        barrier.wait(timeout=10)
        try:
            register_model_release(
                SessionLocal,
                deployment_id=deployment_id,
                model_release=_release(version),
            )
            return "accepted"
        except ModelReleaseError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(advance, (2, 3)))

    with SessionLocal() as db:
        state = db.get(VisionModelReleaseState, deployment_id)
        if state is None or state.highest_release_version != 3:
            raise AssertionError("Concurrent model release registration did not preserve version 3")
        assert_model_release_current(
            db,
            deployment_id=deployment_id,
            model_release=_release(3),
        )
        try:
            assert_model_release_current(
                db,
                deployment_id=deployment_id,
                model_release=_release(2),
            )
        except ModelReleaseError:
            db.rollback()
        else:
            raise AssertionError("A superseded model release passed the runtime guard")

        try:
            db.execute(
                text(
                    "UPDATE vision_model_release_states "
                    "SET highest_release_version = 1 WHERE deployment_id = :deployment_id"
                ),
                {"deployment_id": deployment_id},
            )
            db.commit()
        except DBAPIError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL allowed the model high-water mark to move backwards")

        try:
            db.execute(
                text("DELETE FROM vision_model_release_states WHERE deployment_id = :deployment_id"),
                {"deployment_id": deployment_id},
            )
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL allowed deletion of persistent model trust state")

        event = db.execute(
            select(VisionModelReleaseEvent)
            .where(VisionModelReleaseEvent.deployment_id == deployment_id)
            .order_by(VisionModelReleaseEvent.id.asc())
        ).scalars().first()
        if event is None:
            raise AssertionError("Accepted model release did not create an audit event")
        try:
            db.execute(
                text("UPDATE vision_model_release_events SET reason = 'tampered' WHERE id = :event_id"),
                {"event_id": event.id},
            )
            db.commit()
        except IntegrityError:
            db.rollback()
        else:
            raise AssertionError("PostgreSQL allowed mutation of model release audit events")

    try:
        register_model_release(
            SessionLocal,
            deployment_id=deployment_id,
            model_release=_release(1),
        )
    except ModelReleaseError:
        pass
    else:
        raise AssertionError("PostgreSQL accepted an explicit rollback to release version 1")

    print(
        "PostgreSQL ONNX model anti-rollback smoke passed: "
        f"concurrent outcomes={outcomes}, high-water mark=3, stale runtime rejected, "
        "state monotonicity and append-only audit enforced."
    )


if __name__ == "__main__":
    main()
