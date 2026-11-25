import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import VisionModelReleaseEvent, VisionModelReleaseState
from app.vision_model_release import (
    ModelReleaseError,
    assert_model_release_current,
    register_model_release,
)


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    VisionModelReleaseState.__table__.create(engine)
    VisionModelReleaseEvent.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield factory
    engine.dispose()


def release(version: int, *, digest: str | None = None, model_id: str = "shelf-detector", key_id: str = "release-a"):
    return {
        "model_id": model_id,
        "release_version": version,
        "key_id": key_id,
        "manifest_sha256": digest or f"{version:064x}",
        "detector_sha256": "a" * 64,
        "embedding_sha256": None,
    }


def test_model_release_registry_accepts_first_release_and_exact_retry(session_factory):
    accepted = release(1)

    register_model_release(session_factory, deployment_id="store-edge-a", model_release=accepted)
    register_model_release(session_factory, deployment_id="store-edge-a", model_release=accepted)

    with session_factory() as db:
        state = db.get(VisionModelReleaseState, "store-edge-a")
        events = db.scalars(select(VisionModelReleaseEvent)).all()

    assert state is not None
    assert state.highest_release_version == 1
    assert state.manifest_sha256 == accepted["manifest_sha256"]
    assert [event.decision for event in events] == ["ACCEPTED"]


def test_model_release_registry_advances_only_to_a_strictly_higher_version(session_factory):
    first = release(4)
    second = release(5, key_id="release-b")

    register_model_release(session_factory, deployment_id="edge-a", model_release=first)
    register_model_release(session_factory, deployment_id="edge-a", model_release=second)

    with session_factory() as db:
        state = db.get(VisionModelReleaseState, "edge-a")
        events = db.scalars(select(VisionModelReleaseEvent).order_by(VisionModelReleaseEvent.id)).all()

    assert state.highest_release_version == 5
    assert state.key_id == "release-b"
    assert [event.decision for event in events] == ["ACCEPTED", "ACCEPTED"]


def test_model_release_registry_rejects_rollback_and_records_attempt(session_factory):
    register_model_release(session_factory, deployment_id="edge-a", model_release=release(8))

    with pytest.raises(ModelReleaseError, match="rollback"):
        register_model_release(session_factory, deployment_id="edge-a", model_release=release(7))

    with session_factory() as db:
        state = db.get(VisionModelReleaseState, "edge-a")
        events = db.scalars(select(VisionModelReleaseEvent).order_by(VisionModelReleaseEvent.id)).all()

    assert state.highest_release_version == 8
    assert [event.decision for event in events] == ["ACCEPTED", "REJECTED_ROLLBACK"]


def test_model_release_registry_rejects_same_version_with_different_manifest(session_factory):
    register_model_release(session_factory, deployment_id="edge-a", model_release=release(3))

    with pytest.raises(ModelReleaseError, match="same release version"):
        register_model_release(
            session_factory,
            deployment_id="edge-a",
            model_release=release(3, digest="b" * 64),
        )

    with session_factory() as db:
        state = db.get(VisionModelReleaseState, "edge-a")
        events = db.scalars(select(VisionModelReleaseEvent).order_by(VisionModelReleaseEvent.id)).all()

    assert state.manifest_sha256 == release(3)["manifest_sha256"]
    assert events[-1].decision == "REJECTED_VERSION_COLLISION"


def test_model_release_registry_rejects_model_identity_change(session_factory):
    register_model_release(session_factory, deployment_id="edge-a", model_release=release(2))

    with pytest.raises(ModelReleaseError, match="model identity"):
        register_model_release(
            session_factory,
            deployment_id="edge-a",
            model_release=release(3, model_id="different-detector"),
        )

    with session_factory() as db:
        state = db.get(VisionModelReleaseState, "edge-a")
    assert state.model_id == "shelf-detector"
    assert state.highest_release_version == 2


def test_runtime_guard_requires_exact_persisted_release(session_factory):
    approved = release(9)
    register_model_release(session_factory, deployment_id="edge-a", model_release=approved)

    with session_factory() as db:
        assert_model_release_current(db, deployment_id="edge-a", model_release=approved)
        with pytest.raises(ModelReleaseError, match="no longer current"):
            assert_model_release_current(
                db,
                deployment_id="edge-a",
                model_release=release(8),
            )


def test_runtime_guard_fails_closed_when_release_state_is_missing(session_factory):
    with session_factory() as db:
        with pytest.raises(ModelReleaseError, match="not registered"):
            assert_model_release_current(
                db,
                deployment_id="missing-edge",
                model_release=release(1),
            )
