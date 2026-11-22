"""PostgreSQL concurrency and database-guard smoke for ONNX model anti-rollback."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from app.models import VisionModelReleaseEvent, VisionModelReleaseState
from app.vision_model_release import (
    ModelReleaseError,
    assert_model_release_current,
    register_model_release,
)


def _expect_guard(db, statement: str, parameters: dict, expected_message: str) -> None:
    try:
        db.execute(text(statement), parameters)
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        if expected_message not in str(exc.orig):
            raise AssertionError(
                f"Expected database guard '{expected_message}', received: {exc.orig}"
            ) from exc
    else:
        raise AssertionError(f"PostgreSQL did not enforce database guard: {expected_message}")


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
    deployment_id = "ci-model-release-runtime-role"
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

        _expect_guard(
            db,
            "UPDATE vision_model_release_states SET highest_release_version = 1 "
            "WHERE deployment_id = :deployment_id",
            {"deployment_id": deployment_id},
            "vision model release state must advance monotonically",
        )
        _expect_guard(
            db,
            "DELETE FROM vision_model_release_states WHERE deployment_id = :deployment_id",
            {"deployment_id": deployment_id},
            "vision model release high-water marks cannot be deleted",
        )
        _expect_guard(
            db,
            "TRUNCATE vision_model_release_states, vision_model_release_events",
            {},
            "vision model release trust tables cannot be truncated",
        )

        event = db.execute(
            select(VisionModelReleaseEvent)
            .where(VisionModelReleaseEvent.deployment_id == deployment_id)
            .order_by(VisionModelReleaseEvent.id.asc())
        ).scalars().first()
        if event is None:
            raise AssertionError("Accepted model release did not create an audit event")
        _expect_guard(
            db,
            "UPDATE vision_model_release_events SET reason = 'tampered' WHERE id = :event_id",
            {"event_id": event.id},
            "vision model release events are append-only",
        )
        _expect_guard(
            db,
            "DELETE FROM vision_model_release_events WHERE id = :event_id",
            {"event_id": event.id},
            "vision model release events are append-only",
        )
        _expect_guard(
            db,
            "TRUNCATE vision_model_release_events",
            {},
            "vision model release trust tables cannot be truncated",
        )

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
