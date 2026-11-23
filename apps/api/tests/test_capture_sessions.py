import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from io import BytesIO
from PIL import Image

from app.database import Base, get_db
from app import models
from app.main import app
from app import main as main_module

ENGINE = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Session = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


def _valid_image_bytes(image_format="JPEG"):
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=(20, 80, 140)).save(buffer, format=image_format)
    return buffer.getvalue()


def override_get_db():
    db = Session()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_database():
    previous = app.dependency_overrides.get(get_db)
    Base.metadata.drop_all(bind=ENGINE)
    Base.metadata.create_all(bind=ENGINE)
    app.dependency_overrides[get_db] = override_get_db
    yield
    if previous is None:
        app.dependency_overrides.pop(get_db, None)
    else:
        app.dependency_overrides[get_db] = previous
    Base.metadata.drop_all(bind=ENGINE)


def seed_shelves():
    db = Session()
    store = models.Store(code="CAP-01", name="Capture test store")
    db.add(store)
    db.flush()
    zone = models.Zone(store_id=store.id, name="Aisle 1")
    db.add(zone)
    db.flush()
    shelf = models.Shelf(zone_id=zone.id, code="A1-01")
    other_shelf = models.Shelf(zone_id=zone.id, code="A1-02")
    db.add_all([shelf, other_shelf])
    db.commit()
    result = (shelf.id, other_shelf.id)
    db.close()
    return result


def test_capture_session_create_list_and_close():
    shelf_id, _ = seed_shelves()
    with TestClient(app) as client:
        created = client.post("/api/v1/capture-sessions", json={
            "shelf_id": shelf_id,
            "source_type": "mobile",
            "source_device_id": "device-pseudonym-01",
            "capture_mode": "burst",
        })
        assert created.status_code == 201
        session = created.json()
        assert session["shelf_id"] == shelf_id
        assert session["source_type"] == "mobile"
        assert session["ended_at"] is None

        listed = client.get("/api/v1/capture-sessions", params={"shelf_id": shelf_id, "include_closed": False})
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [session["id"]]

        closed = client.post(f"/api/v1/capture-sessions/{session['id']}/close")
        assert closed.status_code == 200
        assert closed.json()["ended_at"] is not None

        closed_again = client.post(f"/api/v1/capture-sessions/{session['id']}/close")
        assert closed_again.status_code == 200
        assert closed_again.json()["ended_at"] == closed.json()["ended_at"]


def test_session_cannot_be_attached_to_another_shelf(tmp_path, monkeypatch):
    shelf_id, other_shelf_id = seed_shelves()
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    with TestClient(app) as client:
        created = client.post("/api/v1/capture-sessions", json={
            "shelf_id": shelf_id,
            "source_type": "fixed_camera",
            "capture_mode": "single",
        })
        assert created.status_code == 201
        session_id = created.json()["id"]

        response = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(other_shelf_id), "capture_session_id": str(session_id)},
            files={"image": ("shelf.jpg", b"\xff\xd8\xff" + b"x" * 20, "image/jpeg")},
        )
        assert response.status_code == 422
        assert response.json()["detail"] == "Capture session does not belong to this shelf"


def test_upload_links_image_to_open_capture_session(tmp_path, monkeypatch):
    shelf_id, _ = seed_shelves()
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    with TestClient(app) as client:
        created = client.post("/api/v1/capture-sessions", json={
            "shelf_id": shelf_id,
            "source_type": "robot",
            "source_device_id": "robot-pseudonym-02",
            "capture_mode": "video_sample",
        })
        assert created.status_code == 201
        session_id = created.json()["id"]

        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_id), "capture_session_id": str(session_id)},
            files={"image": ("frame.jpg", _valid_image_bytes(), "image/jpeg")},
        )
        assert uploaded.status_code == 201
        assert uploaded.json()["capture_session_id"] == session_id

        closed = client.post(f"/api/v1/capture-sessions/{session_id}/close")
        assert closed.status_code == 200
        rejected = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_id), "capture_session_id": str(session_id)},
            files={"image": ("late-frame.jpg", _valid_image_bytes(), "image/jpeg")},
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"] == "Capture session is closed"


def test_upload_and_close_both_request_capture_session_row_lock(tmp_path, monkeypatch):
    from sqlalchemy.orm import Query

    shelf_id, _ = seed_shelves()
    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    locked_models = []
    original_with_for_update = Query.with_for_update

    def recording_with_for_update(query, *args, **kwargs):
        locked_models.extend(
            description.get("entity")
            for description in query.column_descriptions
        )
        return original_with_for_update(query, *args, **kwargs)

    monkeypatch.setattr(Query, "with_for_update", recording_with_for_update)

    with TestClient(app) as client:
        created = client.post("/api/v1/capture-sessions", json={
            "shelf_id": shelf_id,
            "source_type": "mobile",
            "capture_mode": "single",
        })
        assert created.status_code == 201
        session_id = created.json()["id"]

        uploaded = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(shelf_id), "capture_session_id": str(session_id)},
            files={"image": ("frame.jpg", _valid_image_bytes(), "image/jpeg")},
        )
        assert uploaded.status_code == 201

        closed = client.post(f"/api/v1/capture-sessions/{session_id}/close")
        assert closed.status_code == 200

    assert locked_models.count(models.CaptureSession) == 2


def test_reviewed_training_candidates_group_by_capture_session():
    shelf_id, _ = seed_shelves()
    db = Session()
    store_id = db.query(models.Zone.store_id).join(models.Shelf, models.Shelf.zone_id == models.Zone.id).filter(models.Shelf.id == shelf_id).scalar()
    session = models.CaptureSession(
        store_id=store_id, shelf_id=shelf_id, source_type="mobile",
        capture_mode="burst", started_at=models.utc_now(),
    )
    db.add(session)
    db.flush()
    product = models.Product(sku="CAP-SKU-1", name="Capture product", is_active=True)
    db.add(product)
    db.flush()
    image = models.ShelfImage(
        shelf_id=shelf_id, capture_session_id=session.id,
        original_filename="frame.jpg", storage_path="/tmp/capture-session-frame.jpg",
        mime_type="image/jpeg", file_size_bytes=100, sha256="f" * 64,
    )
    db.add(image)
    db.flush()
    detection = models.ShelfImageDetection(
        shelf_image_id=image.id, product_id=product.id, label="product",
        confidence=0.95, x_min=0.1, y_min=0.1, x_max=0.8, y_max=0.8,
        model_version="detector-v1", sku_match_status="MATCHED",
    )
    db.add(detection)
    db.flush()
    db.add(models.DetectionSkuReview(
        detection_id=detection.id, previous_product_id=product.id,
        selected_product_id=product.id, decision="CONFIRMED",
    ))
    db.commit()
    session_id = session.id
    db.close()

    with TestClient(app) as client:
        response = client.get("/api/v1/training-candidates/reviewed")
    assert response.status_code == 200
    candidate = response.json()[0]
    assert candidate["capture_session_id"] == session_id
    assert candidate["capture_group_key"] == f"session:{session_id}"
    assert "same capture session" in candidate["split_policy"]

def test_capture_session_listing_is_store_scoped_even_with_foreign_shelf_filter(monkeypatch):
    from types import SimpleNamespace

    shelf_id, _ = seed_shelves()
    db = Session()
    own_store_id = (
        db.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == shelf_id)
        .scalar()
    )
    foreign_store = models.Store(code="CAP-FOREIGN", name="Foreign capture store")
    db.add(foreign_store)
    db.flush()
    foreign_zone = models.Zone(store_id=foreign_store.id, name="Foreign aisle")
    db.add(foreign_zone)
    db.flush()
    foreign_shelf = models.Shelf(zone_id=foreign_zone.id, code="FOREIGN-01")
    db.add(foreign_shelf)
    db.flush()

    own_session = models.CaptureSession(
        store_id=own_store_id,
        shelf_id=shelf_id,
        source_type="mobile",
        capture_mode="single",
        started_at=models.utc_now(),
    )
    foreign_session = models.CaptureSession(
        store_id=foreign_store.id,
        shelf_id=foreign_shelf.id,
        source_type="fixed_camera",
        capture_mode="single",
        started_at=models.utc_now(),
    )
    db.add_all([own_session, foreign_session])
    db.commit()
    own_session_id = own_session.id
    foreign_shelf_id = foreign_shelf.id

    supervisor = SimpleNamespace(id=17, role="SUPERVISOR", store_id=own_store_id)
    monkeypatch.setattr(
        main_module,
        "_request_user",
        lambda session, request: supervisor,
    )
    request = SimpleNamespace()
    try:
        own_store_sessions = main_module.list_capture_sessions(request, db=db)
        foreign_shelf_sessions = main_module.list_capture_sessions(
            request,
            shelf_id=foreign_shelf_id,
            db=db,
        )

        assert [item.id for item in own_store_sessions] == [own_session_id]
        assert foreign_shelf_sessions == []
        assert all(item.store_id == own_store_id for item in own_store_sessions)
    finally:
        db.close()


def test_image_upload_hides_foreign_and_missing_capture_session_ids(monkeypatch):
    from types import SimpleNamespace

    own_shelf_id, _ = seed_shelves()
    db = Session()
    own_store_id = (
        db.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == own_shelf_id)
        .scalar()
    )
    foreign_store = models.Store(
        code="CAP-UPLOAD-FOREIGN",
        name="Foreign capture session store",
    )
    db.add(foreign_store)
    db.flush()
    foreign_zone = models.Zone(
        store_id=foreign_store.id,
        name="Foreign aisle",
    )
    db.add(foreign_zone)
    db.flush()
    foreign_shelf = models.Shelf(
        zone_id=foreign_zone.id,
        code="FOREIGN-UPLOAD-01",
    )
    db.add(foreign_shelf)
    db.flush()
    foreign_session = models.CaptureSession(
        store_id=foreign_store.id,
        shelf_id=foreign_shelf.id,
        source_type="fixed_camera",
        capture_mode="single",
        started_at=models.utc_now(),
    )
    db.add(foreign_session)
    db.commit()
    foreign_session_id = foreign_session.id
    db.close()

    supervisor = SimpleNamespace(
        id=17,
        role="SUPERVISOR",
        store_id=own_store_id,
    )
    monkeypatch.setattr(
        main_module,
        "_request_user",
        lambda _db, _request: supervisor,
    )

    with TestClient(app) as client:
        foreign = client.post(
            "/api/v1/shelf-images",
            data={
                "shelf_id": str(own_shelf_id),
                "capture_session_id": str(foreign_session_id),
            },
            files={"image": ("frame.jpg", b"invalid", "image/jpeg")},
        )
        missing = client.post(
            "/api/v1/shelf-images",
            data={
                "shelf_id": str(own_shelf_id),
                "capture_session_id": "2147483000",
            },
            files={"image": ("frame.jpg", b"invalid", "image/jpeg")},
        )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {
        "detail": "Capture session not found"
    }
    with Session() as db:
        assert db.query(models.ShelfImage).count() == 0


def test_foreign_shelf_preflight_is_tenant_filtered_for_create_routes(monkeypatch):
    from types import SimpleNamespace

    own_shelf_id, _ = seed_shelves()
    db = Session()
    own_store_id = (
        db.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == own_shelf_id)
        .scalar()
    )
    foreign_store = models.Store(code="CAP-PREFLIGHT-FOREIGN", name="Foreign preflight store")
    db.add(foreign_store)
    db.flush()
    foreign_zone = models.Zone(store_id=foreign_store.id, name="Foreign preflight aisle")
    db.add(foreign_zone)
    db.flush()
    foreign_shelf = models.Shelf(zone_id=foreign_zone.id, code="FOREIGN-PREFLIGHT-01")
    db.add(foreign_shelf)
    db.commit()
    foreign_shelf_id = foreign_shelf.id
    foreign_zone_id = foreign_zone.id
    db.close()

    supervisor = SimpleNamespace(id=29, role="SUPERVISOR", store_id=own_store_id)
    monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: supervisor)

    with TestClient(app) as client:
        foreign_capture = client.post("/api/v1/capture-sessions", json={
            "shelf_id": foreign_shelf_id,
            "source_type": "mobile",
            "capture_mode": "single",
        })
        missing_capture = client.post("/api/v1/capture-sessions", json={
            "shelf_id": 2147483000,
            "source_type": "mobile",
            "capture_mode": "single",
        })
        foreign_shelf_create = client.post("/api/v1/shelves", json={
            "zone_id": foreign_zone_id,
            "code": "SHOULD-NOT-BE-CREATED",
        })
        missing_zone_create = client.post("/api/v1/shelves", json={
            "zone_id": 2147483000,
            "code": "SHOULD-NOT-BE-CREATED",
        })

    assert foreign_capture.status_code == missing_capture.status_code == 404
    assert foreign_capture.json() == missing_capture.json() == {"detail": "Shelf not found"}
    assert foreign_shelf_create.status_code == missing_zone_create.status_code == 404
    assert foreign_shelf_create.json() == missing_zone_create.json() == {"detail": "Zone not found"}
    with Session() as db:
        assert db.query(models.CaptureSession).count() == 0
        assert db.query(models.Shelf).filter_by(code="SHOULD-NOT-BE-CREATED").count() == 0


def test_shelf_image_upload_hides_foreign_and_missing_shelf_ids(tmp_path, monkeypatch):
    from types import SimpleNamespace

    own_shelf_id, _ = seed_shelves()
    db = Session()
    own_store_id = (
        db.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == own_shelf_id)
        .scalar()
    )
    foreign_store = models.Store(code="CAP-UPLOAD-SHELF-FOREIGN", name="Foreign shelf upload store")
    db.add(foreign_store)
    db.flush()
    foreign_zone = models.Zone(store_id=foreign_store.id, name="Foreign aisle")
    db.add(foreign_zone)
    db.flush()
    foreign_shelf = models.Shelf(zone_id=foreign_zone.id, code="FOREIGN-UPLOAD-SHELF")
    db.add(foreign_shelf)
    db.commit()
    foreign_shelf_id = foreign_shelf.id
    db.close()

    monkeypatch.setattr(main_module.settings, "image_storage_path", str(tmp_path))
    supervisor = SimpleNamespace(id=31, role="SUPERVISOR", store_id=own_store_id)
    monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: supervisor)

    with TestClient(app) as client:
        foreign = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": str(foreign_shelf_id)},
            files={"image": ("frame.jpg", _valid_image_bytes(), "image/jpeg")},
        )
        missing = client.post(
            "/api/v1/shelf-images",
            data={"shelf_id": "2147483000"},
            files={"image": ("frame.jpg", _valid_image_bytes(), "image/jpeg")},
        )

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Shelf not found"}
    with Session() as db:
        assert db.query(models.ShelfImage).count() == 0


def test_observation_consensus_hides_foreign_and_missing_shelf_ids(monkeypatch):
    from types import SimpleNamespace

    own_shelf_id, _ = seed_shelves()
    db = Session()
    own_store_id = (
        db.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == own_shelf_id)
        .scalar()
    )
    foreign_store = models.Store(code="CAP-CONSENSUS-FOREIGN", name="Foreign consensus store")
    db.add(foreign_store)
    db.flush()
    foreign_zone = models.Zone(store_id=foreign_store.id, name="Foreign aisle")
    db.add(foreign_zone)
    db.flush()
    foreign_shelf = models.Shelf(zone_id=foreign_zone.id, code="FOREIGN-CONSENSUS")
    db.add(foreign_shelf)
    db.commit()
    foreign_shelf_id = foreign_shelf.id
    db.close()

    supervisor = SimpleNamespace(id=32, role="SUPERVISOR", store_id=own_store_id)
    monkeypatch.setattr(main_module, "_request_user", lambda _db, _request: supervisor)

    with TestClient(app) as client:
        foreign = client.get(f"/api/v1/shelves/{foreign_shelf_id}/observation-consensus")
        missing = client.get("/api/v1/shelves/2147483000/observation-consensus")
        own = client.get(f"/api/v1/shelves/{own_shelf_id}/observation-consensus")

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json() == {"detail": "Shelf not found"}
    assert own.status_code == 200


def test_planogram_shelf_scope_hides_foreign_and_missing_shelves():
    from types import SimpleNamespace
    from fastapi import HTTPException

    own_shelf_id, _ = seed_shelves()
    db = Session()
    foreign_store = models.Store(code="CAP-PLANOGRAM-FOREIGN", name="Foreign planogram store")
    db.add(foreign_store)
    db.flush()
    foreign_zone = models.Zone(store_id=foreign_store.id, name="Foreign planogram aisle")
    db.add(foreign_zone)
    db.flush()
    foreign_shelf = models.Shelf(zone_id=foreign_zone.id, code="FOREIGN-PLANOGRAM")
    db.add(foreign_shelf)
    db.commit()
    foreign_shelf_id = foreign_shelf.id
    own_store_id = (
        db.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == own_shelf_id)
        .scalar()
    )
    actor = SimpleNamespace(role="SUPERVISOR", store_id=own_store_id)

    try:
        assert main_module._planogram_shelf_scope(db, own_shelf_id, actor).id == own_shelf_id
        with pytest.raises(HTTPException) as foreign_error:
            main_module._planogram_shelf_scope(db, foreign_shelf_id, actor)
        with pytest.raises(HTTPException) as missing_error:
            main_module._planogram_shelf_scope(db, 2147483000, actor)
        assert foreign_error.value.status_code == 404
        assert foreign_error.value.detail == "Shelf not found"
        assert missing_error.value.status_code == 404
        assert missing_error.value.detail == "Shelf not found"
    finally:
        db.close()
