from datetime import date, timedelta, timezone
import math
from pathlib import Path
from uuid import uuid4
import hashlib

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, case, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import func
from jwt import InvalidTokenError

from app.config import settings
from app.database import get_db, SessionLocal
from app import models
from app.security import hash_password, verify_password, create_access_token, decode_access_token
from app.product_text import (
    CatalogueProduct, normalize_product_text, rank_product_catalogue_candidates,
)
from app.replenishment_policy import ShelfRefillInput, suggest_shelf_refill
from app.demand_forecasting import DemandForecastInput, forecast_demand
from app.stockout_risk import StockoutRiskInput, assess_stockout_risk
from app.replenishment_planning import build_replenishment_plan
from app.replenishment_workload import summarize_workload
from app.warehouse_slotting import recommend_warehouse_slotting, recommend_physical_slot
from app.packaging_units import calculate_replenishment_packs
from app.pallet_rotation import evaluate_pallet_rotation, PalletRotationInputError
from app.pallet_rotation_windows import recommend_low_traffic_window
from app.hourly_patterns import build_weekday_hour_profile
from app.hourly_demand_forecast import forecast_hourly_demand
from app.sku_review_evaluation import build_reviewed_prediction_report
from app.sales_import import parse_daily_sales_csv
from app.sales_import_hourly import parse_hourly_sales_csv, parse_hourly_traffic_csv
from app.schemas import (
    ObservationCreate, ObservationRead, ShelfCreate, ShelfRead,
    StoreCreate, StoreRead, ZoneCreate, ZoneRead,
    ProductCreate, ProductRead, ShelfProductCreate, ShelfProductRead,
    InventorySnapshotCreate, InventorySnapshotRead, ReplenishmentRecommendationRead,
    DailySalesRecordCreate, DailySalesRecordRead, SalesSource,
    HourlySalesRecordCreate, HourlySalesRecordRead, HourlyStoreTrafficRecordCreate, HourlyStoreTrafficRecordRead,
    HourlySalesBatchCreate, HourlyStoreTrafficBatchCreate,
    ReplenishmentTaskCreate, ReplenishmentTaskStatusUpdate, ReplenishmentTaskRead,
    BootstrapAdminCreate, LoginRequest, TokenRead, UserRead, UserCreate, ShelfImageRead,
    ShelfImageDetectionRead, ProductEmbeddingExemplarCreate,
    ProductEmbeddingExemplarReview, ProductEmbeddingExemplarRead,
    DetectionSkuReviewCreate, DetectionSkuReviewRead,
    ShelfImageOCRRunCreate, ShelfImageOCRRunRead, ShelfImageOCREvidenceRead,
    ShelfImageOCRMatchRead,
    ShelfImageFusedEvidenceRead,
    ShelfImageReviewQueueItem, ShelfImageTrainingCandidateRead, CaptureSessionCreate, CaptureSessionRead,
    WarehouseLocationCreate, WarehouseProductProfileCreate, WarehousePlacementCreate,
    ProductPackagingLevelCreate, StorePalletCreate, StorePalletRead,
    PalletRotationPolicyCreate, PalletRotationPolicyRead, PalletRotationPolicyUpdate, PalletRotationEventRead, PalletLifecycleUpdate, PalletRotationSimulationRequest,
)

app = FastAPI(title=settings.app_name, version="0.2.0", description="Operational API for SMART SHELF AI.")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)




PUBLIC_API_PATHS = {"/api/v1/auth/bootstrap", "/api/v1/auth/login"}


@app.middleware("http")
async def require_api_authentication(request: Request, call_next):
    if settings.app_env == "test":
        return await call_next(request)
    if not request.url.path.startswith("/api/v1/") or request.url.path in PUBLIC_API_PATHS:
        return await call_next(request)
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return JSONResponse(status_code=401, content={"detail": "Bearer token required"},
                            headers={"WWW-Authenticate": "Bearer"})
    try:
        claims = decode_access_token(token)
        user_id = int(claims["sub"])
    except (InvalidTokenError, KeyError, TypeError, ValueError):
        return JSONResponse(status_code=401, content={"detail": "Invalid or expired access token"},
                            headers={"WWW-Authenticate": "Bearer"})
    db = SessionLocal()
    try:
        user = db.get(models.User, user_id)
        if user is None or not user.is_active:
            return JSONResponse(status_code=401, content={"detail": "User account is inactive or unavailable"},
                                headers={"WWW-Authenticate": "Bearer"})
        request.state.user_id = user.id
        request.state.user_role = user.role
        method = request.method.upper()
        path = request.url.path
        admin_only = (
            path.startswith("/api/v1/auth/users")
            or (method == "POST" and path in {
                "/api/v1/stores", "/api/v1/zones", "/api/v1/shelves",
                "/api/v1/products", "/api/v1/shelf-products",
                "/api/v1/warehouse/product-profiles", "/api/v1/warehouse/product-packaging",
            })
        )
        supervisor_or_admin = (
            (method == "POST" and (path in {"/api/v1/sales/daily", "/api/v1/sales/import-csv", "/api/v1/warehouse/locations", "/api/v1/warehouse/placements", "/api/v1/warehouse/pallets", "/api/v1/warehouse/pallet-rotation/policies", "/api/v1/warehouse/pallet-rotation/simulate", "/api/v1/sales/hourly", "/api/v1/sales/traffic/hourly", "/api/v1/sales/hourly/batch", "/api/v1/sales/traffic/hourly/batch", "/api/v1/sales/hourly/import-csv", "/api/v1/sales/traffic/hourly/import-csv"} or (path.startswith("/api/v1/warehouse/pallets/") and path.endswith("/events"))))
            or (method == "PATCH" and path.startswith("/api/v1/warehouse/pallet-rotation/policies/"))
            or path == "/api/v1/product-embedding-exemplars"
            or path.startswith("/api/v1/product-embedding-exemplars/")
            or (method == "GET" and path == "/api/v1/training-candidates/reviewed")
            or (method == "GET" and path in {"/api/v1/shelf-image-review-queue", "/api/v1/shelf-image-review-queue/summary", "/api/v1/sku-evaluation/reviewed"})
            or (method == "POST" and path.startswith("/api/v1/shelf-image-detections/"))
            or (
                method == "POST"
                and path.startswith("/api/v1/shelf-images/")
                and (path.endswith("/ocr-runs") or path.endswith("/ocr-matches") or path.endswith("/evidence-fusion"))
            )
        )
        if supervisor_or_admin and user.role not in {"ADMIN", "SUPERVISOR"}:
            return JSONResponse(status_code=403, content={"detail": "Supervisor role required"})
        if admin_only and user.role != "ADMIN":
            return JSONResponse(status_code=403, content={"detail": "Administrator role required"})
        if user.role == "EMPLOYEE":
            allowed_employee_read = (
                method == "GET"
                and path in {"/api/v1/tasks", "/api/v1/auth/me", "/api/v1/dashboard/summary", "/api/v1/shelf-images"}
            )
            allowed_employee_image_upload = method == "POST" and path == "/api/v1/shelf-images"
            allowed_employee_image_content = method == "GET" and path.startswith("/api/v1/shelf-images/") and path.endswith("/content")
            allowed_employee_image_detections = method == "GET" and path.startswith("/api/v1/shelf-images/") and path.endswith("/detections")
            allowed_employee_ocr_evidence = method == "GET" and path.startswith("/api/v1/shelf-images/") and (path.endswith("/ocr-evidence") or path.endswith("/ocr-runs") or path.endswith("/ocr-matches") or path.endswith("/evidence-fusion"))
            allowed_employee_detection_review_history = method == "GET" and path.startswith("/api/v1/shelf-image-detections/") and path.endswith("/reviews")
            allowed_employee_task_update = (
                method == "PATCH"
                and path.startswith("/api/v1/tasks/")
                and path.endswith("/status")
            )
            if not (allowed_employee_read or allowed_employee_task_update or allowed_employee_image_upload or allowed_employee_image_content or allowed_employee_image_detections or allowed_employee_ocr_evidence or allowed_employee_detection_review_history):
                return JSONResponse(status_code=403, content={"detail": "Employee access is limited to assigned tasks"})
        if user.role == "SUPERVISOR" and path.startswith("/api/v1/auth/users"):
            return JSONResponse(status_code=403, content={"detail": "Administrator role required"})
    finally:
        db.close()
    return await call_next(request)


def _request_user(db: Session, request: Request | None):
    user_id = getattr(getattr(request, "state", None), "user_id", None)
    return db.get(models.User, user_id) if user_id is not None else None


def _shelf_image_store_id(db: Session, image_id: int) -> int | None:
    return (
        db.query(models.Zone.store_id)
        .join(models.Shelf, models.Shelf.zone_id == models.Zone.id)
        .join(models.ShelfImage, models.ShelfImage.shelf_id == models.Shelf.id)
        .filter(models.ShelfImage.id == image_id)
        .scalar()
    )


def _enforce_store_scope(actor: models.User | None, store_id: int) -> None:
    if actor is not None and actor.role != "ADMIN" and actor.store_id != store_id:
        raise HTTPException(status_code=403, detail="Access to this store is not allowed")


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok", "service": "smart-shelf-ai-api", "environment": settings.app_env}


@app.get("/health/ready", tags=["system"])
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Database unavailable") from exc
    return {"status": "ready", "database": "connected"}


@app.post("/api/v1/stores", response_model=StoreRead, status_code=201, tags=["stores"])
def create_store(payload: StoreCreate, db: Session = Depends(get_db)):
    if db.query(models.Store).filter_by(code=payload.code).first():
        raise HTTPException(status_code=409, detail="Store code already exists")
    item = models.Store(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/stores", response_model=list[StoreRead], tags=["stores"])
def list_stores(request: Request, db: Session = Depends(get_db)):
    query = db.query(models.Store)
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN":
        query = query.filter(models.Store.id == actor.store_id)
    return query.order_by(models.Store.id).all()


@app.post("/api/v1/zones", response_model=ZoneRead, status_code=201, tags=["zones"])
def create_zone(payload: ZoneCreate, db: Session = Depends(get_db)):
    if not db.get(models.Store, payload.store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    item = models.Zone(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.post("/api/v1/shelves", response_model=ShelfRead, status_code=201, tags=["shelves"])
def create_shelf(payload: ShelfCreate, db: Session = Depends(get_db)):
    if not db.get(models.Zone, payload.zone_id):
        raise HTTPException(status_code=404, detail="Zone not found")
    item = models.Shelf(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/shelves", response_model=list[ShelfRead], tags=["shelves"])
def list_shelves(request: Request, db: Session = Depends(get_db)):
    query = db.query(models.Shelf).join(models.Zone, models.Shelf.zone_id == models.Zone.id)
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN":
        query = query.filter(models.Zone.store_id == actor.store_id)
    return query.order_by(models.Shelf.id).all()


@app.post("/api/v1/observations", response_model=ObservationRead, status_code=201, tags=["observations"])
def create_observation(payload: ObservationCreate, request: Request, db: Session = Depends(get_db)):
    shelf_scope = (
        db.query(models.Shelf)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == payload.shelf_id)
        .first()
    )
    if shelf_scope is None:
        raise HTTPException(status_code=404, detail="Shelf not found")
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN" and shelf_scope.zone.store_id != actor.store_id:
        raise HTTPException(status_code=403, detail="Access to this shelf is not allowed")
    data = payload.model_dump()
    if data["observed_at"] is None:
        data["observed_at"] = models.utc_now()
    elif data["observed_at"].tzinfo is None:
        data["observed_at"] = data["observed_at"].replace(tzinfo=timezone.utc)
    item = models.Observation(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/observations", response_model=list[ObservationRead], tags=["observations"])
def list_observations(
    shelf_id: int | None = None,
    limit: int = 100,
    request: Request = None,
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    query = (
        db.query(models.Observation)
        .join(models.Shelf, models.Observation.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
    )
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN":
        query = query.filter(models.Zone.store_id == actor.store_id)
    if shelf_id is not None:
        query = query.filter(models.Observation.shelf_id == shelf_id)
    return query.order_by(models.Observation.observed_at.desc()).limit(limit).all()


@app.post("/api/v1/capture-sessions", response_model=CaptureSessionRead, status_code=201, tags=["computer-vision"])
def create_capture_session(payload: CaptureSessionCreate, request: Request, db: Session = Depends(get_db)):
    actor = _request_user(db, request)
    shelf = db.query(models.Shelf).join(models.Zone, models.Shelf.zone_id == models.Zone.id).filter(models.Shelf.id == payload.shelf_id).first()
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf not found")
    store_id = shelf.zone.store_id
    _enforce_store_scope(actor, store_id)
    if actor is not None and actor.role == "EMPLOYEE":
        raise HTTPException(status_code=403, detail="Supervisor role required to create capture sessions")
    started_at = payload.started_at or models.utc_now()
    if started_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="started_at must include a timezone")
    item = models.CaptureSession(
        store_id=store_id, shelf_id=shelf.id, source_type=payload.source_type,
        source_device_id=payload.source_device_id, capture_mode=payload.capture_mode,
        started_at=started_at, created_by_user_id=actor.id if actor else None,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/capture-sessions", response_model=list[CaptureSessionRead], tags=["computer-vision"])
def list_capture_sessions(request: Request, shelf_id: int | None = None, include_closed: bool = True, limit: int = 100, db: Session = Depends(get_db)):
    actor = _request_user(db, request)
    query = db.query(models.CaptureSession)
    if actor is not None and actor.role != "ADMIN":
        query = query.filter(models.CaptureSession.store_id == actor.store_id)
    if shelf_id is not None:
        query = query.filter(models.CaptureSession.shelf_id == shelf_id)
    if not include_closed:
        query = query.filter(models.CaptureSession.ended_at.is_(None))
    return query.order_by(models.CaptureSession.started_at.desc()).limit(max(1, min(limit, 500))).all()


@app.post("/api/v1/capture-sessions/{session_id}/close", response_model=CaptureSessionRead, tags=["computer-vision"])
def close_capture_session(session_id: int, request: Request, db: Session = Depends(get_db)):
    actor = _request_user(db, request)
    item = db.get(models.CaptureSession, session_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Capture session not found")
    _enforce_store_scope(actor, item.store_id)
    if actor is not None and actor.role == "EMPLOYEE":
        raise HTTPException(status_code=403, detail="Supervisor role required to close capture sessions")
    if item.ended_at is None:
        item.ended_at = models.utc_now()
        db.commit()
        db.refresh(item)
    return item


@app.post("/api/v1/shelf-images", response_model=ShelfImageRead, status_code=201, tags=["computer-vision"])
async def upload_shelf_image(
    request: Request,
    shelf_id: int = Form(...),
    capture_session_id: int | None = Form(default=None),
    image: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Store a validated shelf photograph; analysis is queued for a later CV stage."""
    shelf = (
        db.query(models.Shelf)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == shelf_id)
        .first()
    )
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf not found")
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN" and shelf.zone.store_id != actor.store_id:
        raise HTTPException(status_code=403, detail="Access to this shelf is not allowed")

    capture_session = None
    if capture_session_id is not None:
        capture_session = db.get(models.CaptureSession, capture_session_id)
        if capture_session is None:
            raise HTTPException(status_code=404, detail="Capture session not found")
        if capture_session.shelf_id != shelf.id or capture_session.store_id != shelf.zone.store_id:
            raise HTTPException(status_code=422, detail="Capture session does not belong to this shelf")
        if capture_session.ended_at is not None:
            raise HTTPException(status_code=409, detail="Capture session is closed")

    allowed_types = {
        "image/jpeg": (".jpg", lambda data: data.startswith(b"\xff\xd8\xff")),
        "image/png": (".png", lambda data: data.startswith(b"\x89PNG\r\n\x1a\n")),
        "image/webp": (".webp", lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"),
    }
    mime_type = (image.content_type or "").lower()
    if mime_type not in allowed_types:
        raise HTTPException(status_code=415, detail="Only JPEG, PNG and WebP images are accepted")

    content = await image.read(settings.max_image_upload_bytes + 1)
    if not content:
        raise HTTPException(status_code=422, detail="Uploaded image is empty")
    if len(content) > settings.max_image_upload_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds the configured upload size limit")
    extension, signature_check = allowed_types[mime_type]
    if not signature_check(content):
        raise HTTPException(status_code=415, detail="Image content does not match its declared format")

    image_id = uuid4().hex
    directory = Path(settings.image_storage_path) / str(shelf.zone.store_id)
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{image_id}{extension}"
    destination.write_bytes(content)
    captured_at = models.utc_now()
    record = models.ShelfImage(
        shelf_id=shelf.id,
        capture_session_id=capture_session.id if capture_session else None,
        uploaded_by=actor.id if actor else None,
        original_filename=(Path(image.filename or "capture").name[:255]),
        storage_path=str(destination),
        mime_type=mime_type,
        file_size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
        analysis_status="PENDING",
        captured_at=captured_at,
    )
    try:
        db.add(record)
        db.commit()
        db.refresh(record)
    except Exception:
        db.rollback()
        destination.unlink(missing_ok=True)
        raise
    return record


@app.get("/api/v1/shelf-images", response_model=list[ShelfImageRead], tags=["computer-vision"])
def list_shelf_images(
    request: Request,
    shelf_id: int | None = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = (
        db.query(models.ShelfImage)
        .join(models.Shelf, models.ShelfImage.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
    )
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN":
        query = query.filter(models.Zone.store_id == actor.store_id)
    if shelf_id is not None:
        query = query.filter(models.ShelfImage.shelf_id == shelf_id)
    return query.order_by(models.ShelfImage.created_at.desc()).limit(max(1, min(limit, 500))).all()


@app.get("/api/v1/shelf-images/{image_id}/content", tags=["computer-vision"])
def get_shelf_image_content(image_id: int, request: Request, db: Session = Depends(get_db)):
    item = (
        db.query(models.ShelfImage)
        .join(models.Shelf, models.ShelfImage.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .filter(models.ShelfImage.id == image_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, _shelf_image_store_id(db, image_id))
    path = Path(item.storage_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored image file is unavailable")
    return FileResponse(path, media_type=item.mime_type, filename=item.original_filename, content_disposition_type="inline")


@app.post(
    "/api/v1/shelf-images/{image_id}/retry",
    response_model=ShelfImageRead,
    tags=["computer-vision"],
)
def retry_shelf_image_analysis(
    image_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Requeue a failed image analysis for an authorized store supervisor."""
    item = db.get(models.ShelfImage, image_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    actor = _request_user(db, request)
    if actor is not None and actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="Supervisor role required")
    _enforce_store_scope(actor, _shelf_image_store_id(db, image_id))
    if item.analysis_status != "FAILED":
        raise HTTPException(status_code=409, detail="Only failed image analyses can be retried")
    item.analysis_status = "PENDING"
    item.analysis_error = None
    item.analysis_started_at = None
    item.analysis_completed_at = None
    item.model_version = None
    db.commit()
    db.refresh(item)
    return item


@app.get(
    "/api/v1/shelf-images/{image_id}/detections",
    response_model=list[ShelfImageDetectionRead],
    tags=["computer-vision"],
)
def list_shelf_image_detections(
    image_id: int,
    request: Request,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    """Return persisted model detections for an image, scoped to the user's store."""
    image_record = (
        db.query(models.ShelfImage)
        .join(models.Shelf, models.ShelfImage.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .filter(models.ShelfImage.id == image_id)
        .first()
    )
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, _shelf_image_store_id(db, image_id))
    return (
        db.query(models.ShelfImageDetection)
        .filter(models.ShelfImageDetection.shelf_image_id == image_id)
        .order_by(models.ShelfImageDetection.id)
        .limit(max(1, min(limit, 500)))
        .all()
    )


@app.post("/api/v1/shelf-images/{image_id}/ocr-matches", response_model=list[ShelfImageOCRMatchRead], tags=["computer-vision"])
def match_shelf_image_ocr_to_catalogue(image_id: int, request: Request, db: Session = Depends(get_db)):
    """Rank active catalogue candidates for OCR text grouped by product detection."""
    image_record = db.get(models.ShelfImage, image_id)
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, _shelf_image_store_id(db, image_id))

    run = (
        db.query(models.ShelfImageOCRRun)
        .filter(models.ShelfImageOCRRun.shelf_image_id == image_id,
                models.ShelfImageOCRRun.status == "COMPLETED")
        .order_by(models.ShelfImageOCRRun.id.desc())
        .first()
    )
    if run is None:
        raise HTTPException(status_code=409, detail="No completed OCR run exists for this image")

    existing = (
        db.query(models.ShelfImageOCRMatch)
        .filter(models.ShelfImageOCRMatch.run_id == run.id)
        .order_by(models.ShelfImageOCRMatch.detection_id.asc())
        .all()
    )
    if existing:
        return existing

    evidence = (
        db.query(models.ShelfImageOCREvidence)
        .filter(models.ShelfImageOCREvidence.run_id == run.id,
                models.ShelfImageOCREvidence.detection_id.is_not(None))
        .order_by(models.ShelfImageOCREvidence.id.asc())
        .all()
    )
    grouped = {}
    for item in evidence:
        grouped.setdefault(item.detection_id, []).append(item)

    products = db.query(models.Product).filter(models.Product.is_active.is_(True)).all()
    catalogue = [
        CatalogueProduct(product.id, product.sku, product.name, product.brand, product.unit)
        for product in products
    ]
    results = []
    for detection_id, regions in grouped.items():
        observed_text = " ".join(item.text.strip() for item in regions if item.text.strip())
        confidence = min(item.confidence for item in regions)
        if confidence < 0.65 or not observed_text:
            match = None
            status, suggested_id, top_score, margin, candidates = "UNKNOWN", None, None, None, []
        else:
            match = rank_product_catalogue_candidates(observed_text, catalogue)
            status = match.status
            suggested_id = match.product_id
            top_score = match.score
            margin = match.margin
            candidates = [
                {"product_id": item.product_id, "score": item.score, "reasons": list(item.reasons)}
                for item in match.candidates
            ]
        row = models.ShelfImageOCRMatch(
            run_id=run.id,
            detection_id=detection_id,
            suggested_product_id=suggested_id,
            observed_text=observed_text,
            ocr_confidence=confidence,
            status=status,
            top_score=top_score,
            margin=margin,
            candidates=candidates,
        )
        db.add(row)
        results.append(row)

    db.commit()
    for row in results:
        db.refresh(row)
    return results


@app.get("/api/v1/shelf-images/{image_id}/ocr-matches", response_model=list[ShelfImageOCRMatchRead], tags=["computer-vision"])
def list_shelf_image_ocr_matches(image_id: int, request: Request, limit: int = 500, db: Session = Depends(get_db)):
    """List persisted OCR catalogue suggestions for an image."""
    image_record = db.get(models.ShelfImage, image_id)
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    _enforce_store_scope(_request_user(db, request), _shelf_image_store_id(db, image_id))
    return (
        db.query(models.ShelfImageOCRMatch)
        .join(models.ShelfImageOCRRun, models.ShelfImageOCRMatch.run_id == models.ShelfImageOCRRun.id)
        .filter(models.ShelfImageOCRRun.shelf_image_id == image_id)
        .order_by(models.ShelfImageOCRMatch.id.desc())
        .limit(max(1, min(limit, 1000))).all()
    )



@app.post("/api/v1/shelf-images/{image_id}/evidence-fusion", response_model=list[ShelfImageFusedEvidenceRead], tags=["computer-vision"])
def fuse_shelf_image_evidence(image_id: int, request: Request, db: Session = Depends(get_db)):
    """Persist conservative visual/OCR fusion for the latest completed OCR run."""
    from app.product_evidence_fusion import fuse_product_evidence
    from app.product_matching import ProductCandidate, ProductMatch
    from app.product_text import OCRText, TextCandidate, TextMatch

    image_record = db.get(models.ShelfImage, image_id)
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, _shelf_image_store_id(db, image_id))

    run = (
        db.query(models.ShelfImageOCRRun)
        .filter(models.ShelfImageOCRRun.shelf_image_id == image_id,
                models.ShelfImageOCRRun.status == "COMPLETED")
        .order_by(models.ShelfImageOCRRun.id.desc())
        .first()
    )
    if run is None:
        raise HTTPException(status_code=409, detail="No completed OCR run exists for this image")

    existing = (
        db.query(models.ShelfImageFusedEvidence)
        .filter(models.ShelfImageFusedEvidence.ocr_run_id == run.id)
        .order_by(models.ShelfImageFusedEvidence.detection_id.asc())
        .all()
    )
    if existing:
        return existing

    text_rows = {
        row.detection_id: row
        for row in db.query(models.ShelfImageOCRMatch)
        .filter(models.ShelfImageOCRMatch.run_id == run.id).all()
    }
    detections = (
        db.query(models.ShelfImageDetection)
        .filter(models.ShelfImageDetection.shelf_image_id == image_id)
        .order_by(models.ShelfImageDetection.id.asc()).all()
    )
    results = []
    for detection in detections:
        text_row = text_rows.get(detection.id)
        visual_status = detection.sku_match_status or "UNKNOWN"
        visual = ProductMatch(
            status=visual_status,
            product_id=detection.product_id if visual_status == "MATCHED" else None,
            similarity=detection.sku_similarity,
            margin=detection.sku_match_margin,
            candidates=(),
        )
        if text_row is None:
            text = TextMatch("UNKNOWN", None, None, None, ())
            ocr = None
        else:
            candidates = tuple(
                TextCandidate(
                    product_id=int(item["product_id"]),
                    score=float(item["score"]),
                    reasons=tuple(item.get("reasons", [])),
                )
                for item in (text_row.candidates or [])
            )
            text = TextMatch(
                status=text_row.status,
                product_id=text_row.suggested_product_id,
                score=text_row.top_score,
                margin=text_row.margin,
                candidates=candidates,
            )
            ocr = OCRText(text=text_row.observed_text or "sem texto", confidence=text_row.ocr_confidence) if (text_row.observed_text or "").strip() else None
            if ocr is None:
                text = TextMatch("UNKNOWN", None, None, None, ())

        fused = fuse_product_evidence(visual, text, ocr)
        result = models.ShelfImageFusedEvidence(
            ocr_run_id=run.id,
            detection_id=detection.id,
            status=fused.status,
            suggested_product_id=fused.suggested_product_id,
            visual_product_id=fused.visual_product_id,
            text_product_id=fused.text_product_id,
            visual_status=visual.status,
            text_status=text.status,
            visual_similarity=visual.similarity,
            text_score=text.score,
            ocr_confidence=fused.ocr_confidence,
            visual_model_version=detection.embedding_model_version or detection.model_version,
            ocr_provider=run.provider,
            ocr_model_version=run.model_version,
            reason=fused.reason,
        )
        db.add(result)
        results.append(result)

    db.commit()
    for result in results:
        db.refresh(result)
    return results



@app.get(
    "/api/v1/shelf-image-review-queue/summary",
    response_model=dict[str, int],
    tags=["computer-vision"],
)
def get_shelf_image_review_queue_summary(
    request: Request,
    db: Session = Depends(get_db),
):
    """Count pending human reviews by fusion state, scoped to the actor's store."""
    statuses = ("CONSENSUS", "VISUAL_ONLY", "TEXT_ONLY", "CONFLICT", "AMBIGUOUS", "UNKNOWN")
    actor = _request_user(db, request)
    latest_review_at = (
        db.query(func.max(models.DetectionSkuReview.created_at))
        .filter(models.DetectionSkuReview.detection_id == models.ShelfImageDetection.id)
        .correlate(models.ShelfImageDetection)
        .scalar_subquery()
    )
    query = (
        db.query(models.ShelfImageFusedEvidence.status, func.count(models.ShelfImageFusedEvidence.id))
        .join(models.ShelfImageDetection, models.ShelfImageFusedEvidence.detection_id == models.ShelfImageDetection.id)
        .join(models.ShelfImage, models.ShelfImageDetection.shelf_image_id == models.ShelfImage.id)
        .join(models.Shelf, models.ShelfImage.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .filter(or_(
            latest_review_at.is_(None),
            latest_review_at < models.ShelfImageFusedEvidence.created_at,
        ))
    )
    if actor is not None and actor.role != "ADMIN":
        query = query.filter(models.Zone.store_id == actor.store_id)
    counts = dict(query.group_by(models.ShelfImageFusedEvidence.status).all())
    return {status: int(counts.get(status, 0)) for status in statuses}


@app.get("/api/v1/sku-evaluation/reviewed", tags=["computer-vision"])
def get_reviewed_sku_evaluation(
    request: Request,
    store_id: int | None = None,
    model_version: str | None = None,
    db: Session = Depends(get_db),
):
    """Evaluate historical SKU suggestions against human review decisions."""
    actor = _request_user(db, request)
    if actor is None and settings.app_env != "test":
        raise HTTPException(status_code=401, detail="Authenticated user required")
    if actor is not None:
        if actor.role not in {"ADMIN", "SUPERVISOR"}:
            raise HTTPException(status_code=403, detail="Supervisor role required")
        if actor.role != "ADMIN":
            if actor.store_id is None:
                raise HTTPException(status_code=403, detail="User is not associated with a store")
            if store_id is not None and store_id != actor.store_id:
                raise HTTPException(status_code=403, detail="Access to this store is not allowed")
            store_id = actor.store_id
    if model_version is not None and not model_version.strip():
        raise HTTPException(status_code=422, detail="model_version cannot be empty")
    return build_reviewed_prediction_report(
        db,
        store_id=store_id,
        model_version=model_version.strip() if model_version else None,
    )


@app.get(
    "/api/v1/shelf-image-review-queue",
    response_model=list[ShelfImageReviewQueueItem],
    tags=["computer-vision"],
)
def list_shelf_image_review_queue(
    request: Request,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Return fused detections awaiting a human decision, scoped to the actor's store."""
    allowed_statuses = {"CONSENSUS", "VISUAL_ONLY", "TEXT_ONLY", "CONFLICT", "AMBIGUOUS", "UNKNOWN"}
    if status is not None and status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Unsupported evidence-fusion status")
    actor = _request_user(db, request)
    query = (
        db.query(models.ShelfImageFusedEvidence, models.ShelfImageDetection, models.ShelfImage, models.Shelf)
        .join(models.ShelfImageDetection, models.ShelfImageFusedEvidence.detection_id == models.ShelfImageDetection.id)
        .join(models.ShelfImage, models.ShelfImageDetection.shelf_image_id == models.ShelfImage.id)
        .join(models.Shelf, models.ShelfImage.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
    )
    latest_review_at = (
        db.query(func.max(models.DetectionSkuReview.created_at))
        .filter(models.DetectionSkuReview.detection_id == models.ShelfImageDetection.id)
        .correlate(models.ShelfImageDetection)
        .scalar_subquery()
    )
    query = query.filter(or_(
        latest_review_at.is_(None),
        latest_review_at < models.ShelfImageFusedEvidence.created_at,
    ))
    if actor is not None and actor.role != "ADMIN":
        query = query.filter(models.Zone.store_id == actor.store_id)
    if status is not None:
        query = query.filter(models.ShelfImageFusedEvidence.status == status)
    priority = case(
        (models.ShelfImageFusedEvidence.status == "CONFLICT", 0),
        (models.ShelfImageFusedEvidence.status == "AMBIGUOUS", 1),
        (models.ShelfImageFusedEvidence.status == "TEXT_ONLY", 2),
        (models.ShelfImageFusedEvidence.status == "UNKNOWN", 3),
        (models.ShelfImageFusedEvidence.status == "VISUAL_ONLY", 4),
        else_=5,
    )
    rows = query.order_by(
        priority.asc(),
        models.ShelfImageFusedEvidence.created_at.asc(),
        models.ShelfImageFusedEvidence.id.asc(),
    ).offset(max(0, offset)).limit(max(1, min(limit, 250))).all()
    return [
        {
            "fused_evidence_id": evidence.id,
            "detection_id": detection.id,
            "shelf_image_id": image.id,
            "shelf_id": shelf.id,
            "shelf_code": shelf.code,
            "image_filename": image.original_filename,
            "status": evidence.status,
            "suggested_product_id": evidence.suggested_product_id,
            "visual_product_id": evidence.visual_product_id,
            "text_product_id": evidence.text_product_id,
            "detection_label": detection.label,
            "detection_confidence": detection.confidence,
            "x_min": detection.x_min,
            "y_min": detection.y_min,
            "x_max": detection.x_max,
            "y_max": detection.y_max,
            "visual_similarity": evidence.visual_similarity,
            "text_score": evidence.text_score,
            "ocr_confidence": evidence.ocr_confidence,
            "visual_model_version": evidence.visual_model_version,
            "ocr_provider": evidence.ocr_provider,
            "ocr_model_version": evidence.ocr_model_version,
            "reason": evidence.reason,
            "created_at": evidence.created_at,
        }
        for evidence, detection, image, shelf in rows
    ]


@app.get(
    "/api/v1/training-candidates/reviewed",
    response_model=list[ShelfImageTrainingCandidateRead],
    tags=["computer-vision"],
)
def list_reviewed_training_candidates(
    request: Request,
    product_id: int | None = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """List human-labelled image crops eligible for dataset curation, never auto-training."""
    actor = _request_user(db, request)
    latest_review_id = (
        db.query(func.max(models.DetectionSkuReview.id))
        .filter(models.DetectionSkuReview.detection_id == models.ShelfImageDetection.id)
        .correlate(models.ShelfImageDetection)
        .scalar_subquery()
    )
    query = (
        db.query(
            models.DetectionSkuReview,
            models.ShelfImageDetection,
            models.ShelfImage,
            models.Shelf,
            models.Product,
            models.Zone,
        )
        .join(models.ShelfImageDetection, models.DetectionSkuReview.detection_id == models.ShelfImageDetection.id)
        .join(models.ShelfImage, models.ShelfImageDetection.shelf_image_id == models.ShelfImage.id)
        .join(models.Shelf, models.ShelfImage.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .join(models.Product, models.DetectionSkuReview.selected_product_id == models.Product.id)
        .filter(
            models.DetectionSkuReview.id == latest_review_id,
            models.DetectionSkuReview.decision.in_(("CONFIRMED", "CORRECTED")),
            models.DetectionSkuReview.selected_product_id.isnot(None),
            models.Product.is_active.is_(True),
        )
    )
    if actor is not None and actor.role != "ADMIN":
        query = query.filter(models.Zone.store_id == actor.store_id)
    if product_id is not None:
        query = query.filter(models.Product.id == product_id)
    rows = query.order_by(
        models.ShelfImage.captured_at.asc(),
        models.ShelfImage.id.asc(),
        models.ShelfImageDetection.id.asc(),
    ).offset(max(0, offset)).limit(max(1, min(limit, 250))).all()

    candidates = []
    for review, detection, image, shelf, product, zone in rows:
        existing = (
            db.query(models.ProductEmbeddingExemplar.id)
            .filter(
                models.ProductEmbeddingExemplar.product_id == product.id,
                models.ProductEmbeddingExemplar.image_sha256 == image.sha256,
            )
            .first()
        )
        if existing:
            continue
        candidates.append({
            "review_id": review.id,
            "detection_id": detection.id,
            "shelf_image_id": image.id,
            "store_id": zone.store_id,
            "shelf_id": shelf.id,
            "product_id": product.id,
            "sku": product.sku,
            "product_name": product.name,
            "decision": review.decision,
            "reviewed_at": review.created_at,
            "image_sha256": image.sha256,
            "captured_at": image.captured_at,
            "capture_group_key": f"session:{image.capture_session_id}" if image.capture_session_id is not None else f"image:{image.sha256}",
            "capture_session_id": image.capture_session_id,
            "bbox": {
                "x_min": detection.x_min,
                "y_min": detection.y_min,
                "x_max": detection.x_max,
                "y_max": detection.y_max,
            },
            "detector_model_version": detection.model_version,
            "embedding_model_version": detection.embedding_model_version,
            "dataset_status": "CANDIDATE",
            "split_policy": "Keep all crops from the same capture session in one split; legacy images without a session are grouped by SHA-256.",
            "requires_exemplar_approval": True,
        })
    return candidates


@app.get("/api/v1/shelf-images/{image_id}/evidence-fusion", response_model=list[ShelfImageFusedEvidenceRead], tags=["computer-vision"])
def list_shelf_image_fused_evidence(
    image_id: int,
    request: Request,
    limit: int = 500,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    """List persisted fused evidence, optionally filtered by review status."""
    allowed_statuses = {"CONSENSUS", "VISUAL_ONLY", "TEXT_ONLY", "CONFLICT", "AMBIGUOUS", "UNKNOWN"}
    if status is not None and status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Unsupported evidence-fusion status")
    image_record = db.get(models.ShelfImage, image_id)
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    _enforce_store_scope(_request_user(db, request), _shelf_image_store_id(db, image_id))
    query = (
        db.query(models.ShelfImageFusedEvidence)
        .join(models.ShelfImageDetection, models.ShelfImageFusedEvidence.detection_id == models.ShelfImageDetection.id)
        .filter(models.ShelfImageDetection.shelf_image_id == image_id)
    )
    if status is not None:
        query = query.filter(models.ShelfImageFusedEvidence.status == status)
    return query.order_by(models.ShelfImageFusedEvidence.id.desc()).limit(max(1, min(limit, 1000))).all()



@app.post("/api/v1/shelf-images/{image_id}/ocr-runs", response_model=ShelfImageOCRRunRead, status_code=201, tags=["computer-vision"])
def create_shelf_image_ocr_run(image_id: int, payload: ShelfImageOCRRunCreate, request: Request, db: Session = Depends(get_db)):
    """Persist one immutable OCR pass and its per-region detection associations."""
    image_record = db.get(models.ShelfImage, image_id)
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, _shelf_image_store_id(db, image_id))

    detection_ids = {item.detection_id for item in payload.regions if item.detection_id is not None}
    if detection_ids:
        valid_ids = {
            row[0] for row in db.query(models.ShelfImageDetection.id)
            .filter(
                models.ShelfImageDetection.shelf_image_id == image_id,
                models.ShelfImageDetection.id.in_(detection_ids),
            ).all()
        }
        if valid_ids != detection_ids:
            raise HTTPException(status_code=422, detail="Every detection_id must belong to the supplied shelf image")

    run = models.ShelfImageOCRRun(
        shelf_image_id=image_id,
        provider=payload.provider.strip(),
        model_version=payload.model_version.strip(),
        status="COMPLETED",
        created_by_user_id=actor.id if actor else None,
    )
    db.add(run)
    db.flush()
    for item in payload.regions:
        normalized = normalize_product_text(item.text)
        if not normalized:
            raise HTTPException(status_code=422, detail="OCR text must contain letters or digits")
        db.add(models.ShelfImageOCREvidence(
            run_id=run.id,
            detection_id=item.detection_id,
            text=item.text.strip(),
            normalized_text=normalized[:1000],
            confidence=item.confidence,
            x_min=item.x_min,
            y_min=item.y_min,
            x_max=item.x_max,
            y_max=item.y_max,
            association_status="ASSIGNED" if item.detection_id is not None else "UNASSIGNED",
        ))
    db.commit()
    db.refresh(run)
    return run


@app.get("/api/v1/shelf-images/{image_id}/ocr-evidence", response_model=list[ShelfImageOCREvidenceRead], tags=["computer-vision"])
def list_shelf_image_ocr_evidence(image_id: int, request: Request, limit: int = 500, db: Session = Depends(get_db)):
    """List OCR evidence for an image, newest inference run first."""
    image_record = db.get(models.ShelfImage, image_id)
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    _enforce_store_scope(_request_user(db, request), _shelf_image_store_id(db, image_id))
    return (
        db.query(models.ShelfImageOCREvidence)
        .join(models.ShelfImageOCRRun, models.ShelfImageOCREvidence.run_id == models.ShelfImageOCRRun.id)
        .filter(models.ShelfImageOCRRun.shelf_image_id == image_id)
        .order_by(models.ShelfImageOCREvidence.id.desc())
        .limit(max(1, min(limit, 1000))).all()
    )


@app.get("/api/v1/shelf-images/{image_id}/ocr-runs", response_model=list[ShelfImageOCRRunRead], tags=["computer-vision"])
def list_shelf_image_ocr_runs(image_id: int, request: Request, limit: int = 100, db: Session = Depends(get_db)):
    """List OCR inference provenance for a shelf image."""
    image_record = db.get(models.ShelfImage, image_id)
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    _enforce_store_scope(_request_user(db, request), _shelf_image_store_id(db, image_id))
    return (
        db.query(models.ShelfImageOCRRun)
        .filter(models.ShelfImageOCRRun.shelf_image_id == image_id)
        .order_by(models.ShelfImageOCRRun.id.desc())
        .limit(max(1, min(limit, 500))).all()
    )


@app.post(
    "/api/v1/shelf-image-detections/{detection_id}/reviews",
    response_model=DetectionSkuReviewRead,
    status_code=201,
    tags=["computer-vision"],
)


def create_detection_sku_review(
    detection_id: int,
    payload: DetectionSkuReviewCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Append a human SKU decision without overwriting the model's original detection."""
    detection = db.get(models.ShelfImageDetection, detection_id)
    if detection is None:
        raise HTTPException(status_code=404, detail="Detection not found")
    image_record = db.get(models.ShelfImage, detection.shelf_image_id)
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, _shelf_image_store_id(db, image_record.id))

    selected_product_id = payload.selected_product_id
    if payload.decision == "CONFIRMED" and selected_product_id is None:
        selected_product_id = detection.product_id
    if payload.decision == "CORRECTED" and selected_product_id is None:
        raise HTTPException(status_code=422, detail="selected_product_id is required for a correction")
    if payload.decision == "REJECTED" and selected_product_id is not None:
        raise HTTPException(status_code=422, detail="Rejected detections cannot select a product")
    if payload.decision in {"CONFIRMED", "CORRECTED"}:
        if selected_product_id is None:
            raise HTTPException(status_code=422, detail="There is no proposed SKU to confirm")
        product = db.get(models.Product, selected_product_id)
        if product is None or not product.is_active:
            raise HTTPException(status_code=422, detail="Selected product must exist and be active")
        assigned = db.query(models.ShelfProduct.id).filter(
            models.ShelfProduct.shelf_id == image_record.shelf_id,
            models.ShelfProduct.product_id == selected_product_id,
        ).first()
        if assigned is None:
            raise HTTPException(status_code=422, detail="Selected product is not assigned to the detected shelf")

    review = models.DetectionSkuReview(
        detection_id=detection.id,
        previous_product_id=detection.product_id,
        selected_product_id=selected_product_id,
        decision=payload.decision,
        reviewer_user_id=actor.id if actor else None,
        notes=payload.notes,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return review


@app.get(
    "/api/v1/shelf-image-detections/{detection_id}/reviews",
    response_model=list[DetectionSkuReviewRead],
    tags=["computer-vision"],
)
def list_detection_sku_reviews(
    detection_id: int,
    request: Request,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    detection = db.get(models.ShelfImageDetection, detection_id)
    if detection is None:
        raise HTTPException(status_code=404, detail="Detection not found")
    _enforce_store_scope(_request_user(db, request), _shelf_image_store_id(db, detection.shelf_image_id))
    return (
        db.query(models.DetectionSkuReview)
        .filter(models.DetectionSkuReview.detection_id == detection_id)
        .order_by(models.DetectionSkuReview.created_at, models.DetectionSkuReview.id)
        .limit(max(1, min(limit, 500)))
        .all()
    )


@app.post("/api/v1/products", response_model=ProductRead, status_code=201, tags=["products"])
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    if db.query(models.Product).filter_by(sku=payload.sku).first():
        raise HTTPException(status_code=409, detail="Product SKU already exists")
    item = models.Product(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@app.get("/api/v1/products", response_model=list[ProductRead], tags=["products"])
def list_products(active_only: bool = True, limit: int = 100, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 500))
    query = db.query(models.Product)
    if active_only:
        query = query.filter(models.Product.is_active.is_(True))
    return query.order_by(models.Product.name).limit(limit).all()



@app.post(
    "/api/v1/product-embedding-exemplars",
    response_model=ProductEmbeddingExemplarRead,
    status_code=201,
    tags=["computer-vision"],
)
def create_product_embedding_exemplar(
    payload: ProductEmbeddingExemplarCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Register a reference embedding as PENDING; it is not used for matching yet."""
    product = db.get(models.Product, payload.product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")
    actor = _request_user(db, request)
    if payload.shelf_image_id is not None:
        source_image = db.get(models.ShelfImage, payload.shelf_image_id)
        if source_image is None:
            raise HTTPException(status_code=404, detail="Source shelf image not found")
        if source_image.sha256.lower() != payload.image_sha256.lower():
            raise HTTPException(status_code=422, detail="image_sha256 does not match source shelf image")
        _enforce_store_scope(actor, _shelf_image_store_id(db, source_image.id))
    item = models.ProductEmbeddingExemplar(
        product_id=payload.product_id,
        shelf_image_id=payload.shelf_image_id,
        embedding=payload.embedding,
        embedding_dimension=len(payload.embedding),
        model_version=payload.model_version.strip(),
        image_sha256=payload.image_sha256.lower(),
        licence=payload.licence.strip(),
        review_status="PENDING",
        created_by_user_id=actor.id if actor else None,
    )
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="This product/model/image exemplar already exists") from exc
    db.refresh(item)
    return item


@app.get(
    "/api/v1/product-embedding-exemplars",
    response_model=list[ProductEmbeddingExemplarRead],
    tags=["computer-vision"],
)
def list_product_embedding_exemplars(
    product_id: int | None = None,
    review_status: str | None = None,
    model_version: str | None = None,
    limit: int = 100,
    request: Request = None,
    db: Session = Depends(get_db),
):
    if review_status is not None and review_status not in {"PENDING", "APPROVED", "REJECTED"}:
        raise HTTPException(status_code=422, detail="Invalid review_status")
    query = db.query(models.ProductEmbeddingExemplar)
    if product_id is not None:
        query = query.filter(models.ProductEmbeddingExemplar.product_id == product_id)
    if review_status is not None:
        query = query.filter(models.ProductEmbeddingExemplar.review_status == review_status)
    if model_version is not None:
        query = query.filter(models.ProductEmbeddingExemplar.model_version == model_version)
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN":
        query = query.join(
            models.ShelfImage,
            models.ProductEmbeddingExemplar.shelf_image_id == models.ShelfImage.id,
            isouter=True,
        ).join(
            models.Shelf,
            models.ShelfImage.shelf_id == models.Shelf.id,
            isouter=True,
        ).join(
            models.Zone,
            models.Shelf.zone_id == models.Zone.id,
            isouter=True,
        ).filter(
            (
                models.ProductEmbeddingExemplar.shelf_image_id.is_(None)
                & (models.ProductEmbeddingExemplar.created_by_user_id == actor.id)
            )
            | (models.Zone.store_id == actor.store_id)
        )
    return query.order_by(models.ProductEmbeddingExemplar.created_at.desc()).limit(max(1, min(limit, 500))).all()


@app.patch(
    "/api/v1/product-embedding-exemplars/{exemplar_id}/review",
    response_model=ProductEmbeddingExemplarRead,
    tags=["computer-vision"],
)
def review_product_embedding_exemplar(
    exemplar_id: int,
    payload: ProductEmbeddingExemplarReview,
    request: Request,
    db: Session = Depends(get_db),
):
    """Approve or reject a pending exemplar with reviewer attribution."""
    item = db.get(models.ProductEmbeddingExemplar, exemplar_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Embedding exemplar not found")
    actor = _request_user(db, request)
    if item.shelf_image_id is not None:
        _enforce_store_scope(actor, _shelf_image_store_id(db, item.shelf_image_id))
    elif actor is not None and actor.role != "ADMIN" and item.created_by_user_id != actor.id:
        raise HTTPException(status_code=403, detail="Access to this exemplar is not allowed")
    if item.review_status != "PENDING":
        raise HTTPException(status_code=409, detail="Only pending exemplars can be reviewed")
    item.review_status = payload.review_status
    item.review_notes = payload.review_notes
    item.reviewed_by_user_id = actor.id if actor else None
    item.reviewed_at = models.utc_now()
    db.commit()
    db.refresh(item)
    return item


@app.post("/api/v1/shelf-products", response_model=ShelfProductRead, status_code=201, tags=["catalog"])
def assign_product_to_shelf(payload: ShelfProductCreate, db: Session = Depends(get_db)):
    if not db.get(models.Shelf, payload.shelf_id):
        raise HTTPException(status_code=404, detail="Shelf not found")
    if not db.get(models.Product, payload.product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    if db.query(models.ShelfProduct).filter_by(
        shelf_id=payload.shelf_id, product_id=payload.product_id
    ).first():
        raise HTTPException(status_code=409, detail="Product is already assigned to this shelf")
    item = models.ShelfProduct(**payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Shelf/product assignment conflicts with an existing record") from exc
    db.refresh(item)
    return item


@app.get("/api/v1/shelf-products", response_model=list[ShelfProductRead], tags=["catalog"])
def list_shelf_products(
    shelf_id: int | None = None,
    product_id: int | None = None,
    request: Request = None,
    db: Session = Depends(get_db),
):
    query = (
        db.query(models.ShelfProduct)
        .join(models.Shelf, models.ShelfProduct.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
    )
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN":
        query = query.filter(models.Zone.store_id == actor.store_id)
    if shelf_id is not None:
        query = query.filter(models.ShelfProduct.shelf_id == shelf_id)
    if product_id is not None:
        query = query.filter(models.ShelfProduct.product_id == product_id)
    return query.order_by(models.ShelfProduct.shelf_id, models.ShelfProduct.position).all()



@app.post(
    "/api/v1/sales/daily",
    response_model=DailySalesRecordRead,
    status_code=201,
    tags=["sales"],
)
def create_daily_sales_record(
    payload: DailySalesRecordCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Ingest one source-referenced daily product sales aggregate."""
    actor = _request_user(db, request)
    _enforce_store_scope(actor, payload.store_id)
    if not db.get(models.Store, payload.store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, payload.product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")
    item = models.DailySalesRecord(**payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Daily sales external reference already exists") from exc
    db.refresh(item)
    return item


@app.post("/api/v1/sales/hourly", response_model=HourlySalesRecordRead, status_code=201, tags=["sales"])
def create_hourly_sales_record(payload: HourlySalesRecordCreate, request: Request, db: Session = Depends(get_db)):
    actor = _request_user(db, request)
    _enforce_store_scope(actor, payload.store_id)
    if db.get(models.Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, payload.product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")
    item = models.HourlySalesRecord(**payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Hourly sales external reference already exists") from exc
    db.refresh(item)
    return item


@app.post("/api/v1/sales/traffic/hourly", response_model=HourlyStoreTrafficRecordRead, status_code=201, tags=["sales"])
def create_hourly_store_traffic_record(payload: HourlyStoreTrafficRecordCreate, request: Request, db: Session = Depends(get_db)):
    actor = _request_user(db, request)
    _enforce_store_scope(actor, payload.store_id)
    if db.get(models.Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    item = models.HourlyStoreTrafficRecord(**payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Hourly traffic external reference already exists") from exc
    db.refresh(item)
    return item




@app.post("/api/v1/sales/hourly/import-csv", tags=["sales"])
async def import_hourly_sales_csv(
    request: Request,
    store_id: int = Form(...),
    source: SalesSource = Form("IMPORT"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    max_file_bytes = 5 * 1024 * 1024
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only .csv files are accepted")
    payload = await file.read(max_file_bytes + 1)
    if len(payload) > max_file_bytes:
        raise HTTPException(status_code=413, detail="CSV file exceeds the 5 MB limit")
    try:
        rows = parse_hourly_sales_csv(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    product_ids = {row.product_id for row in rows}
    active_ids = {
        item.id for item in db.query(models.Product).filter(
            models.Product.id.in_(product_ids), models.Product.is_active.is_(True)
        ).all()
    }
    missing = sorted(product_ids - active_ids)
    if missing:
        raise HTTPException(status_code=422, detail={"code": "UNKNOWN_OR_INACTIVE_PRODUCTS", "product_ids": missing})
    items = [
        models.HourlySalesRecord(
            store_id=store_id, product_id=row.product_id, business_date=row.business_date,
            hour_of_day=row.hour_of_day, quantity=row.quantity, source=source,
            external_reference=row.external_reference,
        ) for row in rows
    ]
    db.add_all(items)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Hourly sales CSV conflicts with existing records; no rows were saved") from exc
    return {
        "status": "IMPORTED", "store_id": store_id, "source": source,
        "rows_imported": len(items), "product_count": len(product_ids),
        "period_start": min(row.business_date for row in rows),
        "period_end": max(row.business_date for row in rows), "atomic": True,
    }


@app.post("/api/v1/sales/traffic/hourly/import-csv", tags=["sales"])
async def import_hourly_traffic_csv(
    request: Request,
    store_id: int = Form(...),
    source: SalesSource = Form("IMPORT"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    max_file_bytes = 5 * 1024 * 1024
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only .csv files are accepted")
    payload = await file.read(max_file_bytes + 1)
    if len(payload) > max_file_bytes:
        raise HTTPException(status_code=413, detail="CSV file exceeds the 5 MB limit")
    try:
        rows = parse_hourly_traffic_csv(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    items = [
        models.HourlyStoreTrafficRecord(
            store_id=store_id, business_date=row.business_date, hour_of_day=row.hour_of_day,
            customer_count=row.customer_count, source=source, external_reference=row.external_reference,
        ) for row in rows
    ]
    db.add_all(items)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Hourly traffic CSV conflicts with existing records; no rows were saved") from exc
    return {
        "status": "IMPORTED", "store_id": store_id, "source": source,
        "rows_imported": len(items), "period_start": min(row.business_date for row in rows),
        "period_end": max(row.business_date for row in rows), "atomic": True,
    }


@app.get("/api/v1/sales/hourly", response_model=list[HourlySalesRecordRead], tags=["sales"])
def list_hourly_sales_records(
    store_id: int,
    product_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 500,
    request: Request = None,
    db: Session = Depends(get_db),
):
    if not 1 <= limit <= 1000:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 1000")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")
    _enforce_store_scope(_request_user(db, request), store_id)
    query = db.query(models.HourlySalesRecord).filter(models.HourlySalesRecord.store_id == store_id)
    if product_id is not None:
        query = query.filter(models.HourlySalesRecord.product_id == product_id)
    if start_date is not None:
        query = query.filter(models.HourlySalesRecord.business_date >= start_date)
    if end_date is not None:
        query = query.filter(models.HourlySalesRecord.business_date <= end_date)
    return query.order_by(
        models.HourlySalesRecord.business_date.desc(),
        models.HourlySalesRecord.hour_of_day.desc(),
        models.HourlySalesRecord.id.desc(),
    ).limit(limit).all()


@app.get("/api/v1/sales/traffic/hourly", response_model=list[HourlyStoreTrafficRecordRead], tags=["sales"])
def list_hourly_store_traffic_records(
    store_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 500,
    request: Request = None,
    db: Session = Depends(get_db),
):
    if not 1 <= limit <= 1000:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 1000")
    if start_date and end_date and start_date > end_date:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")
    _enforce_store_scope(_request_user(db, request), store_id)
    query = db.query(models.HourlyStoreTrafficRecord).filter(
        models.HourlyStoreTrafficRecord.store_id == store_id
    )
    if start_date is not None:
        query = query.filter(models.HourlyStoreTrafficRecord.business_date >= start_date)
    if end_date is not None:
        query = query.filter(models.HourlyStoreTrafficRecord.business_date <= end_date)
    return query.order_by(
        models.HourlyStoreTrafficRecord.business_date.desc(),
        models.HourlyStoreTrafficRecord.hour_of_day.desc(),
        models.HourlyStoreTrafficRecord.id.desc(),
    ).limit(limit).all()


@app.post("/api/v1/sales/hourly/batch", status_code=201, tags=["sales"])
def create_hourly_sales_batch(payload: HourlySalesBatchCreate, request: Request, db: Session = Depends(get_db)):
    actor = _request_user(db, request)
    store_id = payload.records[0].store_id
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product_ids = {row.product_id for row in payload.records}
    active_ids = {
        item.id for item in db.query(models.Product).filter(
            models.Product.id.in_(product_ids), models.Product.is_active.is_(True)
        ).all()
    }
    missing = sorted(product_ids - active_ids)
    if missing:
        raise HTTPException(status_code=422, detail={"code": "UNKNOWN_OR_INACTIVE_PRODUCTS", "product_ids": missing})
    items = [models.HourlySalesRecord(**row.model_dump()) for row in payload.records]
    db.add_all(items)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Batch conflicts with previously imported hourly sales; no rows were saved") from exc
    return {"status": "IMPORTED", "store_id": store_id, "rows_imported": len(items), "atomic": True}


@app.post("/api/v1/sales/traffic/hourly/batch", status_code=201, tags=["sales"])
def create_hourly_traffic_batch(payload: HourlyStoreTrafficBatchCreate, request: Request, db: Session = Depends(get_db)):
    actor = _request_user(db, request)
    store_id = payload.records[0].store_id
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    items = [models.HourlyStoreTrafficRecord(**row.model_dump()) for row in payload.records]
    db.add_all(items)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Batch conflicts with previously imported hourly traffic; no rows were saved") from exc
    return {"status": "IMPORTED", "store_id": store_id, "rows_imported": len(items), "atomic": True}


@app.get("/api/v1/warehouse/pallet-rotation/hourly-profile", tags=["warehouse"])
def get_pallet_rotation_hourly_profile(
    store_id: int, product_id: int, days: int = 28, source: SalesSource = "POS",
    request: Request = None, db: Session = Depends(get_db),
):
    """Return local-hour demand and traffic averages without filling missing observations."""
    if not 7 <= days <= 90:
        raise HTTPException(status_code=422, detail="days must be between 7 and 90")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")

    start_date = date.today() - timedelta(days=days - 1)
    sales_daily = db.query(
        models.HourlySalesRecord.business_date.label("business_date"),
        models.HourlySalesRecord.hour_of_day.label("hour"),
        func.sum(models.HourlySalesRecord.quantity).label("quantity"),
    ).filter(
        models.HourlySalesRecord.store_id == store_id,
        models.HourlySalesRecord.product_id == product_id,
        models.HourlySalesRecord.business_date >= start_date,
        models.HourlySalesRecord.source == source,
    ).group_by(models.HourlySalesRecord.business_date, models.HourlySalesRecord.hour_of_day).subquery()
    sales_rows = db.query(
        sales_daily.c.hour,
        func.avg(sales_daily.c.quantity).label("average_quantity"),
        func.count(sales_daily.c.business_date).label("observed_days"),
    ).group_by(sales_daily.c.hour).all()

    traffic_daily = db.query(
        models.HourlyStoreTrafficRecord.business_date.label("business_date"),
        models.HourlyStoreTrafficRecord.hour_of_day.label("hour"),
        func.sum(models.HourlyStoreTrafficRecord.customer_count).label("customers"),
    ).filter(
        models.HourlyStoreTrafficRecord.store_id == store_id,
        models.HourlyStoreTrafficRecord.business_date >= start_date,
        models.HourlyStoreTrafficRecord.source == source,
    ).group_by(models.HourlyStoreTrafficRecord.business_date, models.HourlyStoreTrafficRecord.hour_of_day).subquery()
    traffic_rows = db.query(
        traffic_daily.c.hour,
        func.avg(traffic_daily.c.customers).label("average_customers"),
        func.count(traffic_daily.c.business_date).label("observed_days"),
    ).group_by(traffic_daily.c.hour).all()

    sales_by_hour = {int(row.hour): row for row in sales_rows}
    traffic_by_hour = {int(row.hour): row for row in traffic_rows}
    return {
        "store_id": store_id, "product_id": product_id, "period_days": days, "source": source,
        "period_start": start_date, "period_end": date.today(),
        "hour_basis": "STORE_LOCAL_HOUR",
        "hours": [{
            "hour_of_day": hour,
            "average_daily_units": float(sales_by_hour[hour].average_quantity) if hour in sales_by_hour else None,
            "sales_observed_days": int(sales_by_hour[hour].observed_days) if hour in sales_by_hour else 0,
            "average_customers": float(traffic_by_hour[hour].average_customers) if hour in traffic_by_hour else None,
            "traffic_observed_days": int(traffic_by_hour[hour].observed_days) if hour in traffic_by_hour else 0,
        } for hour in range(24)],
        "missing_sales_hours": [hour for hour in range(24) if hour not in sales_by_hour],
        "missing_traffic_hours": [hour for hour in range(24) if hour not in traffic_by_hour],
        "forecast_generated": False, "simulation_only": True,
    }


@app.get("/api/v1/forecasting/hourly-demand", tags=["forecasting"])
def get_hourly_demand_forecast(
    store_id: int,
    product_id: int,
    horizon_days: int = 7,
    history_days: int = 180,
    minimum_observed_days: int = 4,
    source: SalesSource = "POS",
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Return a transparent same-weekday/hour seasonal baseline; read-only."""
    if not 28 <= history_days <= 365:
        raise HTTPException(status_code=422, detail="history_days must be between 28 and 365")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")
    forecast_start = date.today() + timedelta(days=1)
    history_start = forecast_start - timedelta(days=history_days)
    records = db.query(models.HourlySalesRecord).filter(
        models.HourlySalesRecord.store_id == store_id,
        models.HourlySalesRecord.product_id == product_id,
        models.HourlySalesRecord.source == source,
        models.HourlySalesRecord.business_date >= history_start,
        models.HourlySalesRecord.business_date < forecast_start,
    ).all()
    try:
        result = forecast_hourly_demand(
            records,
            forecast_start=forecast_start,
            horizon_days=horizon_days,
            minimum_observed_days=minimum_observed_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "store_id": store_id,
        "product_id": product_id,
        "source": source,
        "history_start": history_start,
        "history_end": forecast_start - timedelta(days=1),
        **result,
    }


@app.get("/api/v1/warehouse/pallet-rotation/weekday-hourly-profile", tags=["warehouse"])
def get_pallet_rotation_weekday_hourly_profile(
    store_id: int,
    product_id: int,
    days: int = 56,
    source: SalesSource = "POS",
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Return separate weekday/hour averages for one source; missing observations remain null."""
    if not 14 <= days <= 180:
        raise HTTPException(status_code=422, detail="days must be between 14 and 180")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    sales_rows = db.query(models.HourlySalesRecord).filter(
        models.HourlySalesRecord.store_id == store_id,
        models.HourlySalesRecord.product_id == product_id,
        models.HourlySalesRecord.business_date >= start_date,
        models.HourlySalesRecord.business_date <= end_date,
        models.HourlySalesRecord.source == source,
    ).all()
    traffic_rows = db.query(models.HourlyStoreTrafficRecord).filter(
        models.HourlyStoreTrafficRecord.store_id == store_id,
        models.HourlyStoreTrafficRecord.business_date >= start_date,
        models.HourlyStoreTrafficRecord.business_date <= end_date,
        models.HourlyStoreTrafficRecord.source == source,
    ).all()
    profile = build_weekday_hour_profile(sales_rows, traffic_rows)
    return {
        "store_id": store_id,
        "product_id": product_id,
        "period_days": days,
        "period_start": start_date,
        "period_end": end_date,
        "weekday_basis": "ISO_WEEKDAY_MONDAY_ZERO",
        "source": source,
        "hour_basis": "STORE_LOCAL_HOUR",
        "observed_profile": profile,
        "forecast_generated": False,
        "simulation_only": True,
    }


@app.get("/api/v1/warehouse/pallet-rotation/window-plan", tags=["warehouse"])
def plan_pallet_rotation_window(
    store_id: int,
    product_id: int,
    pallet_id: int,
    current_hour: int,
    residual_base_units: float,
    duration_hours: int = 1,
    days: int = 28,
    source: SalesSource = "POS",
    minimum_observed_days: int = 7,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Suggest a low-traffic local-hour window from historical sales and traffic."""
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    pallet = db.query(models.StorePallet).filter_by(
        id=pallet_id, store_id=store_id, product_id=product_id
    ).first()
    if pallet is None:
        raise HTTPException(status_code=404, detail="Pallet not found for this store and product")
    if pallet.status not in {"ON_DISPLAY", "PARTIAL"} or pallet.location_type != "SALES_FLOOR":
        raise HTTPException(status_code=422, detail="Only a pallet on the sales floor can be planned")
    if float(pallet.base_quantity) != residual_base_units:
        raise HTTPException(status_code=409, detail="Residual quantity differs from the current pallet record; refresh and retry")
    active_policy = db.query(models.PalletRotationPolicy).filter_by(
        store_id=store_id, product_id=product_id, is_enabled=True
    ).first()
    if active_policy is None:
        raise HTTPException(status_code=422, detail="Product has no active pallet rotation policy")
    try:
        profile = get_pallet_rotation_hourly_profile(
            store_id=store_id, product_id=product_id, days=days, source=source, request=request, db=db
        )
        decision = recommend_low_traffic_window(
            profile["hours"],
            current_hour=current_hour,
            duration_hours=duration_hours,
            residual_base_units=residual_base_units,
            minimum_observed_days=minimum_observed_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "store_id": store_id,
        "product_id": product_id,
        "pallet_id": pallet_id,
        "current_hour": current_hour,
        "period_days": days,
        "source": source,
        "minimum_observed_days": minimum_observed_days,
        "decision": {
            "recommendation": decision.recommendation,
            "reason_code": decision.reason_code,
            "explanation": decision.explanation,
            "start_hour": decision.start_hour,
            "duration_hours": decision.duration_hours,
            "projected_consumption_through_window": decision.projected_consumption_through_window,
            "residual_after_consumption": decision.residual_after_consumption,
            "expected_customers_during_window": decision.expected_customers_during_window,
            "observed_sales_days_min": decision.observed_sales_days_min,
            "observed_traffic_days_min": decision.observed_traffic_days_min,
            "historical_profile_only": decision.historical_profile_only,
            "automatic_stock_movement_allowed": False,
        },
        "simulation_only": True,
    }


@app.post("/api/v1/sales/import-csv", tags=["sales"])
async def import_daily_sales_csv(
    request: Request,
    store_id: int = Form(...),
    source: SalesSource = Form("IMPORT"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Import a bounded CSV atomically; every row must be valid."""
    MAX_FILE_BYTES = 5 * 1024 * 1024
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    if file.filename and not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only .csv files are accepted")
    payload = await file.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="CSV file exceeds the 5 MB limit")
    try:
        rows = parse_daily_sales_csv(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    product_ids = {row.product_id for row in rows}
    active_products = {
        product.id
        for product in db.query(models.Product).filter(
            models.Product.id.in_(product_ids),
            models.Product.is_active.is_(True),
        ).all()
    }
    missing_products = sorted(product_ids - active_products)
    if missing_products:
        raise HTTPException(
            status_code=422,
            detail={"code": "UNKNOWN_OR_INACTIVE_PRODUCTS", "product_ids": missing_products},
        )

    items = [
        models.DailySalesRecord(
            store_id=store_id,
            product_id=row.product_id,
            sales_date=row.sales_date,
            quantity=row.quantity,
            source=source,
            external_reference=row.external_reference,
        )
        for row in rows
    ]
    db.add_all(items)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="CSV contains a sales reference already imported for this store, product, date and source; no rows were saved",
        ) from exc
    return {
        "status": "IMPORTED",
        "store_id": store_id,
        "source": source,
        "rows_imported": len(items),
        "product_count": len(product_ids),
        "period_start": min(row.sales_date for row in rows),
        "period_end": max(row.sales_date for row in rows),
        "note": "Import is atomic: all rows were saved together.",
    }


@app.get("/api/v1/sales/daily", response_model=list[DailySalesRecordRead], tags=["sales"])
def list_daily_sales_records(
    store_id: int,
    product_id: int,
    source: SalesSource,
    days: int = 28,
    request: Request = None,
    db: Session = Depends(get_db),
):
    if days < 1 or days > 365:
        raise HTTPException(status_code=422, detail="days must be between 1 and 365")
    _enforce_store_scope(_request_user(db, request), store_id)
    query = db.query(models.DailySalesRecord).filter(
        models.DailySalesRecord.store_id == store_id,
        models.DailySalesRecord.product_id == product_id,
        models.DailySalesRecord.source == source,
    )
    return query.order_by(models.DailySalesRecord.sales_date.desc()).limit(days).all()





@app.get("/api/v1/warehouse/slotting-recommendations", tags=["warehouse"])
def get_warehouse_slotting_recommendations(
    store_id: int,
    source: SalesSource,
    days: int = 28,
    minimum_average_daily_sales: float = 1.0,
    through_date: date | None = None,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Rank high-rotation products for a human-reviewed warehouse slotting decision."""
    if days < 7 or days > 365:
        raise HTTPException(status_code=422, detail="days must be between 7 and 365")
    if (not math.isfinite(minimum_average_daily_sales)
            or minimum_average_daily_sales < 0):
        raise HTTPException(status_code=422, detail="minimum_average_daily_sales must be finite and non-negative")
    _enforce_store_scope(_request_user(db, request), store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")

    end_day = through_date or date.today()
    start_day = end_day - timedelta(days=days - 1)
    rows = (
        db.query(
            models.Product.id.label("product_id"),
            models.Product.sku.label("sku"),
            models.Product.name.label("product_name"),
            func.coalesce(func.sum(models.DailySalesRecord.quantity), 0).label("total_quantity"),
            func.count(func.distinct(models.DailySalesRecord.sales_date)).label("history_days"),
        )
        .join(models.DailySalesRecord, models.DailySalesRecord.product_id == models.Product.id)
        .filter(
            models.Product.is_active.is_(True),
            models.DailySalesRecord.store_id == store_id,
            models.DailySalesRecord.source == source,
            models.DailySalesRecord.sales_date >= start_day,
            models.DailySalesRecord.sales_date <= end_day,
        )
        .group_by(models.Product.id, models.Product.sku, models.Product.name)
        .all()
    )
    result = recommend_warehouse_slotting(
        [{
            "product_id": row.product_id,
            "sku": row.sku,
            "product_name": row.product_name,
            "total_quantity": float(row.total_quantity),
            "history_days": int(row.history_days),
            "expected_days": days,
        } for row in rows],
        minimum_average_daily_sales=minimum_average_daily_sales,
    )
    return {
        "store_id": store_id,
        "source": source,
        "period_start": start_day,
        "period_end": end_day,
        "required_complete_days": days,
        "minimum_average_daily_sales": minimum_average_daily_sales,
        "analysed_products": result.analysed_products,
        "excluded_incomplete_history": result.excluded_incomplete_history,
        "products": list(result.products),
        "read_only": True,
        "policy": "Sugestão de slotting baseada em vendas diárias completas. Não escolhe uma localização física nem move stock; validar capacidade, dimensões, peso, segurança, temperatura e distância real.",
    }


@app.post("/api/v1/warehouse/locations", status_code=201, tags=["warehouse"])
def create_warehouse_location(
    payload: WarehouseLocationCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    _enforce_store_scope(actor, payload.store_id)
    if db.get(models.Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    location = models.WarehouseLocation(**payload.model_dump())
    db.add(location)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A warehouse location with this code already exists in the store") from exc
    db.refresh(location)
    return location


@app.get("/api/v1/warehouse/locations", tags=["warehouse"])
def list_warehouse_locations(
    store_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    return (
        db.query(models.WarehouseLocation)
        .filter(models.WarehouseLocation.store_id == store_id)
        .order_by(models.WarehouseLocation.distance_to_picking_m, models.WarehouseLocation.code)
        .all()
    )


@app.post("/api/v1/warehouse/product-profiles", status_code=201, tags=["warehouse"])
def create_warehouse_product_profile(
    payload: WarehouseProductProfileCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    product = db.get(models.Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if db.query(models.WarehouseProductProfile).filter_by(product_id=payload.product_id).first():
        raise HTTPException(status_code=409, detail="Warehouse profile already exists for this product")
    profile = models.WarehouseProductProfile(**payload.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.post("/api/v1/warehouse/placements", status_code=201, tags=["warehouse"])
def create_warehouse_placement(
    payload: WarehousePlacementCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    location = db.get(models.WarehouseLocation, payload.location_id)
    if location is None:
        raise HTTPException(status_code=404, detail="Warehouse location not found")
    _enforce_store_scope(actor, location.store_id)
    if db.get(models.Product, payload.product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    placement = models.WarehouseProductPlacement(**payload.model_dump())
    db.add(placement)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A placement for this product already exists at this location") from exc
    db.refresh(placement)
    return placement


@app.post("/api/v1/warehouse/product-packaging", status_code=201, tags=["warehouse"])
def create_product_packaging_level(
    payload: ProductPackagingLevelCreate,
    db: Session = Depends(get_db),
):
    product = db.get(models.Product, payload.product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    if payload.package_type == "UNIT" and payload.base_units_per_package != 1:
        raise HTTPException(status_code=422, detail="UNIT packaging must equal exactly one base unit")
    if payload.package_type in {"CASE", "PALLET"} and payload.base_units_per_package <= 1:
        raise HTTPException(status_code=422, detail="CASE and PALLET packaging must contain more than one base unit")
    if db.query(models.ProductPackagingLevel).filter_by(product_id=payload.product_id, code=payload.code).first():
        raise HTTPException(status_code=409, detail="Packaging code already exists for this product")
    if payload.is_replenishment_unit and db.query(models.ProductPackagingLevel).filter_by(
        product_id=payload.product_id, is_replenishment_unit=True, is_active=True
    ).first():
        raise HTTPException(status_code=409, detail="A replenishment unit is already configured for this product")
    if payload.is_ordering_unit and db.query(models.ProductPackagingLevel).filter_by(
        product_id=payload.product_id, is_ordering_unit=True, is_active=True
    ).first():
        raise HTTPException(status_code=409, detail="An ordering unit is already configured for this product")
    level = models.ProductPackagingLevel(**payload.model_dump())
    db.add(level)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Packaging level conflicts with existing product data") from exc
    db.refresh(level)
    return level


@app.get("/api/v1/warehouse/product-packaging", tags=["warehouse"])
def list_product_packaging_levels(
    product_id: int,
    db: Session = Depends(get_db),
):
    if db.get(models.Product, product_id) is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return (
        db.query(models.ProductPackagingLevel)
        .filter(
            models.ProductPackagingLevel.product_id == product_id,
            models.ProductPackagingLevel.is_active.is_(True),
        )
        .order_by(models.ProductPackagingLevel.base_units_per_package)
        .all()
    )


@app.post("/api/v1/warehouse/pallets", response_model=StorePalletRead, status_code=201, tags=["warehouse"])
def register_store_pallet(
    payload: StorePalletCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Register one identified physical pallet; does not change aggregate inventory."""
    actor = _request_user(db, request)
    _enforce_store_scope(actor, payload.store_id)
    if db.get(models.Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, payload.product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")
    level = db.get(models.ProductPackagingLevel, payload.packaging_level_id)
    if level is None or not level.is_active:
        raise HTTPException(status_code=404, detail="Active packaging level not found")
    if level.product_id != payload.product_id or level.package_type != "PALLET":
        raise HTTPException(status_code=422, detail="Packaging level must be a PALLET level belonging to this product")
    if payload.base_quantity > float(level.base_units_per_package):
        raise HTTPException(status_code=422, detail="Pallet quantity cannot exceed configured pallet capacity")
    if payload.status == "ON_DISPLAY" and payload.location_type != "SALES_FLOOR":
        raise HTTPException(status_code=422, detail="ON_DISPLAY pallets must have SALES_FLOOR location type")
    if payload.status in {"READY", "RETURNED", "REBUILDING"} and payload.location_type == "SALES_FLOOR":
        raise HTTPException(status_code=422, detail="This pallet status is incompatible with SALES_FLOOR location")

    pallet = models.StorePallet(**payload.model_dump())
    db.add(pallet)
    try:
        db.flush()
        db.add(models.PalletRotationEvent(
            pallet_id=pallet.id,
            event_type="REGISTERED",
            to_location_type=pallet.location_type,
            to_location_code=pallet.location_code,
            quantity_before=0,
            quantity_after=pallet.base_quantity,
            lot_code=pallet.lot_code,
            expiry_date=pallet.expiry_date,
            reason="Initial pallet registration; no physical movement or aggregate stock adjustment was performed.",
            performed_by_user_id=actor.id if actor else None,
            occurred_at=models.utc_now(),
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pallet code already exists in this store or pallet data conflicts") from exc
    db.refresh(pallet)
    return pallet


@app.get("/api/v1/warehouse/pallets", response_model=list[StorePalletRead], tags=["warehouse"])
def list_store_pallets(
    store_id: int,
    product_id: int | None = None,
    status: str | None = None,
    limit: int = 200,
    request: Request = None,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    allowed_statuses = {"READY", "ON_DISPLAY", "PARTIAL", "RETURNED", "REBUILDING", "EMPTY", "QUARANTINED"}
    if status is not None and status not in allowed_statuses:
        raise HTTPException(status_code=422, detail="Invalid pallet status")
    query = db.query(models.StorePallet).filter(models.StorePallet.store_id == store_id)
    if product_id is not None:
        query = query.filter(models.StorePallet.product_id == product_id)
    if status is not None:
        query = query.filter(models.StorePallet.status == status)
    return query.order_by(models.StorePallet.updated_at.desc(), models.StorePallet.id.desc()).limit(max(1, min(limit, 500))).all()


@app.post("/api/v1/warehouse/pallet-rotation/policies", response_model=PalletRotationPolicyRead, status_code=201, tags=["warehouse"])
def create_pallet_rotation_policy(
    payload: PalletRotationPolicyCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    _enforce_store_scope(actor, payload.store_id)
    if db.get(models.Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, payload.product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")
    if not db.query(models.ProductPackagingLevel).filter_by(
        product_id=payload.product_id, package_type="PALLET", is_active=True
    ).first():
        raise HTTPException(status_code=422, detail="Product requires an active PALLET packaging level")
    policy = models.PalletRotationPolicy(**payload.model_dump())
    db.add(policy)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A pallet rotation policy already exists for this store and product") from exc
    db.refresh(policy)
    return policy


@app.patch("/api/v1/warehouse/pallet-rotation/policies/{policy_id}", response_model=PalletRotationPolicyRead, tags=["warehouse"])
def update_pallet_rotation_policy(
    policy_id: int,
    payload: PalletRotationPolicyUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    policy = db.get(models.PalletRotationPolicy, policy_id)
    if policy is None:
        raise HTTPException(status_code=404, detail="Pallet rotation policy not found")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, policy.store_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(policy, field, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail="Invalid pallet rotation policy") from exc
    db.refresh(policy)
    return policy


@app.get("/api/v1/warehouse/pallet-rotation/policies", response_model=list[PalletRotationPolicyRead], tags=["warehouse"])
def list_pallet_rotation_policies(
    store_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    return db.query(models.PalletRotationPolicy).filter_by(store_id=store_id).order_by(
        models.PalletRotationPolicy.product_id
    ).all()


@app.post("/api/v1/warehouse/pallet-rotation/simulate", tags=["warehouse"])
def simulate_pallet_rotation(
    payload: PalletRotationSimulationRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Evaluate one displayed pallet against registered replacement stock; read-only."""
    actor = _request_user(db, request)
    _enforce_store_scope(actor, payload.store_id)
    if db.get(models.Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")

    pallet = db.query(models.StorePallet).filter_by(
        id=payload.pallet_id, store_id=payload.store_id
    ).first()
    if pallet is None:
        raise HTTPException(status_code=404, detail="Pallet not found")
    if pallet.status not in {"ON_DISPLAY", "PARTIAL"} or pallet.location_type != "SALES_FLOOR":
        raise HTTPException(status_code=422, detail="Only ON_DISPLAY or PARTIAL pallets at SALES_FLOOR can be simulated")

    policy = db.query(models.PalletRotationPolicy).filter_by(
        store_id=payload.store_id, product_id=pallet.product_id, is_enabled=True
    ).first()
    level = db.get(models.ProductPackagingLevel, pallet.packaging_level_id)
    if level is None or not level.is_active or level.package_type != "PALLET":
        raise HTTPException(status_code=422, detail="Pallet packaging level is unavailable or invalid")

    replacement = db.query(models.StorePallet).filter(
        models.StorePallet.store_id == payload.store_id,
        models.StorePallet.product_id == pallet.product_id,
        models.StorePallet.packaging_level_id == pallet.packaging_level_id,
        models.StorePallet.id != pallet.id,
        models.StorePallet.status == "READY",
        models.StorePallet.location_type.in_(["WAREHOUSE", "PREPARATION"]),
        models.StorePallet.base_quantity == level.base_units_per_package,
        or_(models.StorePallet.expiry_date.is_(None), models.StorePallet.expiry_date >= date.today()),
    ).order_by(
        models.StorePallet.expiry_date.asc().nullslast(),
        models.StorePallet.created_at.asc(),
        models.StorePallet.id.asc(),
    ).first()

    try:
        result = evaluate_pallet_rotation(
            product_eligible=policy is not None,
            residual_base_units=pallet.base_quantity,
            pallet_capacity_base_units=level.base_units_per_package,
            threshold_ratio=policy.threshold_ratio if policy else 0.5,
            traffic_level=payload.traffic_level,
            replacement_pallet_available=replacement is not None,
            backroom_capacity_available=payload.backroom_capacity_available,
            conventional_replenishment_minutes=payload.conventional_replenishment_minutes,
            pallet_swap_minutes=payload.pallet_swap_minutes,
            transport_minutes=payload.transport_minutes,
            pallet_rebuild_minutes=payload.pallet_rebuild_minutes,
            labour_cost_per_hour=payload.labour_cost_per_hour,
            forecast_consumption_until_low_traffic=payload.forecast_consumption_until_low_traffic,
        )
    except PalletRotationInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "store_id": payload.store_id,
        "product_id": pallet.product_id,
        "display_pallet": {
            "id": pallet.id,
            "pallet_code": pallet.pallet_code,
            "status": pallet.status,
            "base_quantity": float(pallet.base_quantity),
            "lot_code": pallet.lot_code,
            "expiry_date": pallet.expiry_date,
        },
        "replacement_pallet": None if replacement is None else {
            "id": replacement.id,
            "pallet_code": replacement.pallet_code,
            "base_quantity": float(replacement.base_quantity),
            "lot_code": replacement.lot_code,
            "expiry_date": replacement.expiry_date,
            "location_type": replacement.location_type,
            "location_code": replacement.location_code,
        },
        "policy": None if policy is None else {
            "threshold_ratio": float(policy.threshold_ratio),
            "is_enabled": policy.is_enabled,
        },
        "decision": {
            "recommendation": result.recommendation,
            "reason_code": result.reason_code,
            "explanation": result.explanation,
            "residual_ratio": result.residual_ratio,
            "threshold_ratio": result.threshold_ratio,
            "conventional_cost": result.conventional_cost,
            "swap_cost": result.swap_cost,
            "estimated_minutes_saved": result.estimated_minutes_saved,
            "inputs_complete": result.inputs_complete,
            "automatic_stock_movement_allowed": False,
        },
        "simulation_only": True,
        "backroom_capacity_source": "OPERATOR_CONFIRMED",
    }


@app.get("/api/v1/warehouse/pallets/{pallet_id}/events", response_model=list[PalletRotationEventRead], tags=["warehouse"])
def list_pallet_lifecycle_events(
    pallet_id: int,
    store_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    pallet = db.query(models.StorePallet).filter_by(id=pallet_id, store_id=store_id).first()
    if pallet is None:
        raise HTTPException(status_code=404, detail="Pallet not found")
    return db.query(models.PalletRotationEvent).filter_by(pallet_id=pallet_id).order_by(
        models.PalletRotationEvent.occurred_at, models.PalletRotationEvent.id
    ).all()


@app.post("/api/v1/warehouse/pallets/{pallet_id}/events", response_model=PalletRotationEventRead, status_code=201, tags=["warehouse"])
def record_pallet_lifecycle_update(
    pallet_id: int,
    payload: PalletLifecycleUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Record a supervised, optimistic-concurrency-protected pallet state update."""
    actor = _request_user(db, request)
    pallet = db.query(models.StorePallet).filter_by(id=pallet_id).with_for_update().first()
    if pallet is None:
        raise HTTPException(status_code=404, detail="Pallet not found")
    _enforce_store_scope(actor, pallet.store_id)

    if pallet.status != payload.expected_status or float(pallet.base_quantity) != payload.expected_base_quantity:
        raise HTTPException(status_code=409, detail="Pallet state changed; refresh and retry with the current status and quantity")

    allowed_transitions = {
        "READY": {"ON_DISPLAY", "QUARANTINED"},
        "ON_DISPLAY": {"PARTIAL", "RETURNED", "EMPTY", "QUARANTINED"},
        "PARTIAL": {"RETURNED", "REBUILDING", "ON_DISPLAY", "EMPTY", "QUARANTINED"},
        "RETURNED": {"REBUILDING", "EMPTY", "QUARANTINED"},
        "REBUILDING": {"READY", "EMPTY", "QUARANTINED"},
        "EMPTY": {"QUARANTINED"},
        "QUARANTINED": set(),
    }
    next_status = payload.status or pallet.status
    next_quantity = payload.base_quantity if payload.base_quantity is not None else float(pallet.base_quantity)
    next_location_type = payload.location_type or pallet.location_type
    next_location_code = payload.location_code if payload.location_code is not None else pallet.location_code

    if next_status != pallet.status and next_status not in allowed_transitions[pallet.status]:
        raise HTTPException(status_code=422, detail=f"Invalid pallet transition: {pallet.status} -> {next_status}")
    if (next_status == "EMPTY" and next_quantity != 0) or (next_status != "EMPTY" and next_quantity <= 0):
        raise HTTPException(status_code=422, detail="EMPTY requires zero quantity; all other statuses require positive quantity")
    if next_status == "ON_DISPLAY" and next_location_type != "SALES_FLOOR":
        raise HTTPException(status_code=422, detail="ON_DISPLAY pallets must be at SALES_FLOOR")
    if next_status in {"READY", "RETURNED", "REBUILDING", "EMPTY"} and next_location_type == "SALES_FLOOR":
        raise HTTPException(status_code=422, detail="The requested status is incompatible with SALES_FLOOR")
    if next_quantity > float(db.get(models.ProductPackagingLevel, pallet.packaging_level_id).base_units_per_package):
        raise HTTPException(status_code=422, detail="Pallet quantity exceeds configured pallet capacity")

    old_status = pallet.status
    old_quantity = float(pallet.base_quantity)
    old_location_type = pallet.location_type
    old_location_code = pallet.location_code
    if next_status != old_status:
        event_type = "STATUS_REVIEWED"
    elif next_quantity != old_quantity:
        event_type = "QUANTITY_RECORDED"
    else:
        event_type = "LOCATION_RECORDED"

    pallet.status = next_status
    pallet.base_quantity = next_quantity
    pallet.location_type = next_location_type
    pallet.location_code = next_location_code
    pallet.updated_at = models.utc_now()
    event = models.PalletRotationEvent(
        pallet_id=pallet.id,
        event_type=event_type,
        from_location_type=old_location_type,
        from_location_code=old_location_code,
        to_location_type=next_location_type,
        to_location_code=next_location_code,
        quantity_before=old_quantity,
        quantity_after=next_quantity,
        lot_code=pallet.lot_code,
        expiry_date=pallet.expiry_date,
        reason=payload.reason,
        performed_by_user_id=actor.id if actor else None,
        occurred_at=models.utc_now(),
    )
    db.add(event)
    db.add(pallet)
    db.commit()
    db.refresh(event)
    return event


@app.get("/api/v1/warehouse/replenishment-units", tags=["warehouse"])
def calculate_replenishment_units(
    store_id: int,
    product_id: int,
    required_base_units: float,
    packaging_code: str,
    allow_open_package: bool = False,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Calculate logistics packs needed to move base selling units; this does not define the sales unit."""
    _enforce_store_scope(_request_user(db, request), store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")
    level = db.query(models.ProductPackagingLevel).filter_by(
        product_id=product_id, code=packaging_code, is_active=True
    ).first()
    if level is None:
        raise HTTPException(status_code=404, detail="Active packaging level not found")
    try:
        result = calculate_replenishment_packs(
            required_base_units=required_base_units,
            base_units_per_package=level.base_units_per_package,
            allow_open_package=allow_open_package,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "store_id": store_id,
        "product_id": product_id,
        "product_name": product.name,
        "base_unit": product.unit,
        "packaging_code": level.code,
        "packaging_name": level.name,
        "package_type": level.package_type,
        "base_units_per_package": float(level.base_units_per_package),
        "allow_open_package": allow_open_package,
        **result,
    }


@app.get("/api/v1/warehouse/physical-slotting", tags=["warehouse"])
def get_physical_warehouse_slotting(
    store_id: int,
    product_id: int,
    required_quantity: float,
    request: Request,
    db: Session = Depends(get_db),
):
    """Rank feasible physical bins for an additional quantity; never moves stock."""
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, product_id)
    if product is None or not product.is_active:
        raise HTTPException(status_code=404, detail="Active product not found")
    profile = db.query(models.WarehouseProductProfile).filter_by(product_id=product_id).first()
    profile_data = None if profile is None else {
        "unit_volume_cm3": float(profile.unit_volume_cm3),
        "unit_weight_kg": float(profile.unit_weight_kg),
        "temperature_requirement": profile.temperature_requirement,
        "is_fragile": profile.is_fragile,
        "requires_segregation": profile.requires_segregation,
    }

    locations = db.query(models.WarehouseLocation).filter(
        models.WarehouseLocation.store_id == store_id,
        models.WarehouseLocation.is_active.is_(True),
    ).all()
    placement_rows = (
        db.query(models.WarehouseProductPlacement, models.WarehouseProductProfile)
        .join(models.WarehouseLocation, models.WarehouseProductPlacement.location_id == models.WarehouseLocation.id)
        .outerjoin(models.WarehouseProductProfile, models.WarehouseProductPlacement.product_id == models.WarehouseProductProfile.product_id)
        .filter(
            models.WarehouseLocation.store_id == store_id,
            models.WarehouseProductPlacement.is_active.is_(True),
            models.WarehouseProductPlacement.quantity > 0,
        )
        .all()
    )
    occupancy = {}
    for placement, other_profile in placement_rows:
        item = occupancy.setdefault(placement.location_id, {
            "volume": 0.0, "weight": 0.0, "unknown_profile": False, "products": set()
        })
        item["products"].add(placement.product_id)
        if other_profile is None:
            item["unknown_profile"] = True
        else:
            quantity = float(placement.quantity)
            item["volume"] += quantity * float(other_profile.unit_volume_cm3)
            item["weight"] += quantity * float(other_profile.unit_weight_kg)

    location_inputs = []
    for location in locations:
        current = occupancy.get(location.id, {
            "volume": 0.0, "weight": 0.0, "unknown_profile": False, "products": set()
        })
        location_inputs.append({
            "location_id": location.id,
            "code": location.code,
            "distance_to_picking_m": float(location.distance_to_picking_m),
            "max_volume_cm3": float(location.max_volume_cm3),
            "max_weight_kg": float(location.max_weight_kg),
            "occupied_volume_cm3": None if current["unknown_profile"] else current["volume"],
            "occupied_weight_kg": None if current["unknown_profile"] else current["weight"],
            "temperature_zone": location.temperature_zone,
            "is_active": location.is_active,
            "other_product_count": len(current["products"] - {product_id}),
        })

    try:
        result = recommend_physical_slot(
            product_id=product_id,
            required_quantity=required_quantity,
            product_profile=profile_data,
            locations=location_inputs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "store_id": store_id,
        "product_id": product_id,
        "sku": product.sku,
        "product_name": product.name,
        "required_quantity": required_quantity,
        "status": result.status,
        "candidates": list(result.candidates),
        "rejected_locations": list(result.rejected_locations),
        "automatic_movement_allowed": False,
        "policy": "A quantidade indicada é adicional à ocupação atual. Localizações com stock existente sem perfil dimensional conhecido são excluídas; validar fisicamente antes de qualquer transferência.",
    }


@app.get("/api/v1/forecasting/demand", tags=["forecasting"])
def get_product_demand_forecast(
    store_id: int,
    product_id: int,
    source: SalesSource,
    lead_time_days: float,
    target_cover_days: float = 7.0,
    days: int = 28,
    through_date: date | None = None,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Forecast demand only from complete, explicitly ingested daily source records."""
    if days < 7 or days > 365:
        raise HTTPException(status_code=422, detail="days must be between 7 and 365")
    _enforce_store_scope(_request_user(db, request), store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    end_day = through_date or date.today()
    start_day = end_day - timedelta(days=days - 1)
    records = db.query(models.DailySalesRecord).filter(
        models.DailySalesRecord.store_id == store_id,
        models.DailySalesRecord.product_id == product_id,
        models.DailySalesRecord.source == source,
        models.DailySalesRecord.sales_date >= start_day,
        models.DailySalesRecord.sales_date <= end_day,
    ).all()
    quantities_by_day = {}
    for record in records:
        quantities_by_day[record.sales_date] = quantities_by_day.get(record.sales_date, 0.0) + float(record.quantity)
    missing_days = [
        (start_day + timedelta(days=offset)).isoformat()
        for offset in range(days)
        if start_day + timedelta(days=offset) not in quantities_by_day
    ]
    if missing_days:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INCOMPLETE_DAILY_SALES_HISTORY",
                "message": "Forecast requires an explicit sales record for every calendar day; use quantity 0 for confirmed zero-sales days.",
                "missing_days": missing_days,
            },
        )
    try:
        result = forecast_demand(DemandForecastInput(
            daily_sales=[quantities_by_day[start_day + timedelta(days=offset)] for offset in range(days)],
            lead_time_days=lead_time_days,
            target_cover_days=target_cover_days,
            recent_window_days=days,
            minimum_history_days=7,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "store_id": store_id,
        "product_id": product_id,
        "product_name": product.name,
        "source": source,
        "period_start": start_day,
        "period_end": end_day,
        "forecast": {
            "status": result.status,
            "history_days": result.history_days,
            "average_daily_demand": result.average_daily_demand,
            "daily_demand_stddev": result.daily_demand_stddev,
            "expected_lead_time_demand": result.expected_lead_time_demand,
            "safety_stock": result.safety_stock,
            "reorder_point": result.reorder_point,
            "target_stock": result.target_stock,
            "explanation": result.explanation,
        },
        "policy": "Advisory estimate only; no purchase order, inventory mutation or replenishment task is created.",
    }



@app.get("/api/v1/forecasting/stockout-risk", tags=["forecasting"])
def get_product_stockout_risk(
    store_id: int, product_id: int, source: SalesSource, lead_time_days: float,
    target_cover_days: float = 7.0, days: int = 28,
    through_date: date | None = None, max_inventory_age_minutes: int = 240,
    request: Request = None, db: Session = Depends(get_db),
):
    """Combine complete daily sales history with a fresh inventory snapshot."""
    if days < 7 or days > 365:
        raise HTTPException(status_code=422, detail="days must be between 7 and 365")
    if max_inventory_age_minutes < 1 or max_inventory_age_minutes > 10080:
        raise HTTPException(status_code=422, detail="max_inventory_age_minutes must be between 1 and 10080")
    _enforce_store_scope(_request_user(db, request), store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    product = db.get(models.Product, product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    end_day = through_date or date.today()
    start_day = end_day - timedelta(days=days - 1)
    records = db.query(models.DailySalesRecord).filter(
        models.DailySalesRecord.store_id == store_id,
        models.DailySalesRecord.product_id == product_id,
        models.DailySalesRecord.source == source,
        models.DailySalesRecord.sales_date >= start_day,
        models.DailySalesRecord.sales_date <= end_day,
    ).all()
    by_day = {}
    for record in records:
        by_day[record.sales_date] = by_day.get(record.sales_date, 0.0) + float(record.quantity)
    missing = [(start_day + timedelta(days=i)).isoformat()
               for i in range(days) if start_day + timedelta(days=i) not in by_day]
    if missing:
        raise HTTPException(status_code=409, detail={
            "code": "INCOMPLETE_DAILY_SALES_HISTORY",
            "message": "Risk assessment requires an explicit sales record for every day; use quantity 0 for confirmed zero-sales days.",
            "missing_days": missing,
        })
    try:
        forecast = forecast_demand(DemandForecastInput(
            daily_sales=[by_day[start_day + timedelta(days=i)] for i in range(days)],
            lead_time_days=lead_time_days, target_cover_days=target_cover_days,
            recent_window_days=days, minimum_history_days=7,
        ))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    snapshot = db.query(models.InventorySnapshot).filter(
        models.InventorySnapshot.store_id == store_id,
        models.InventorySnapshot.product_id == product_id,
    ).order_by(models.InventorySnapshot.captured_at.desc(), models.InventorySnapshot.id.desc()).first()
    if snapshot is None:
        return {
            "store_id": store_id, "product_id": product_id, "product_name": product.name,
            "source": source, "period_start": start_day, "period_end": end_day,
            "forecast_status": forecast.status, "inventory_status": "MISSING",
            "risk": {"status": "RISK_UNKNOWN", "risk_level": "UNKNOWN",
                     "days_of_cover": None, "projected_stock_at_receipt": None,
                     "safety_stock_gap": None, "requires_action": True,
                     "explanation": "Não existe snapshot de inventário; atualizar o stock antes de classificar o risco."},
            "policy": "Advisory only; no task, purchase order or inventory movement is created.",
        }
    captured = snapshot.captured_at
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    now = models.utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age = max(0.0, (now - captured).total_seconds() / 60)
    inventory = {"snapshot_id": snapshot.id, "source": snapshot.source,
                 "available_quantity": float(snapshot.available_quantity),
                 "captured_at": snapshot.captured_at, "age_minutes": round(age, 2)}
    if age > max_inventory_age_minutes:
        return {
            "store_id": store_id, "product_id": product_id, "product_name": product.name,
            "source": source, "period_start": start_day, "period_end": end_day,
            "forecast_status": forecast.status, "inventory_status": "STALE",
            "inventory": inventory,
            "risk": {"status": "RISK_UNKNOWN", "risk_level": "UNKNOWN",
                     "days_of_cover": None, "projected_stock_at_receipt": None,
                     "safety_stock_gap": None, "requires_action": True,
                     "explanation": "O snapshot de inventário está desatualizado; atualizar o stock antes de classificar o risco."},
            "policy": "Advisory only; no task, purchase order or inventory movement is created.",
        }
    risk = assess_stockout_risk(StockoutRiskInput(
        available_quantity=float(snapshot.available_quantity),
        average_daily_demand=forecast.average_daily_demand,
        lead_time_days=lead_time_days, safety_stock=forecast.safety_stock,
        forecast_status=forecast.status,
    ))
    return {
        "store_id": store_id, "product_id": product_id, "product_name": product.name,
        "source": source, "period_start": start_day, "period_end": end_day,
        "forecast_status": forecast.status, "inventory_status": "FRESH",
        "inventory": inventory,
        "forecast": {"average_daily_demand": forecast.average_daily_demand,
                     "daily_demand_stddev": forecast.daily_demand_stddev,
                     "expected_lead_time_demand": forecast.expected_lead_time_demand,
                     "safety_stock": forecast.safety_stock,
                     "reorder_point": forecast.reorder_point,
                     "target_stock": forecast.target_stock},
        "risk": {"status": risk.status, "risk_level": risk.risk_level,
                 "days_of_cover": risk.days_of_cover,
                 "projected_stock_at_receipt": risk.projected_stock_at_receipt,
                 "safety_stock_gap": risk.safety_stock_gap,
                 "requires_action": risk.requires_action,
                 "explanation": risk.explanation},
        "policy": "Advisory only; no task, purchase order or inventory movement is created.",
    }


@app.get("/api/v1/forecasting/stockout-risk/portfolio", tags=["forecasting"])
def get_store_stockout_risk_portfolio(
    store_id: int,
    source: SalesSource,
    lead_time_days: float,
    target_cover_days: float = 7.0,
    days: int = 28,
    through_date: date | None = None,
    max_inventory_age_minutes: int = 240,
    limit: int = 100,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Return a bounded, read-only risk portfolio for products assigned to store shelves."""
    if days < 7 or days > 365:
        raise HTTPException(status_code=422, detail="days must be between 7 and 365")
    if max_inventory_age_minutes < 1 or max_inventory_age_minutes > 10080:
        raise HTTPException(status_code=422, detail="max_inventory_age_minutes must be between 1 and 10080")
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")

    _enforce_store_scope(_request_user(db, request), store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")

    product_query = (
        db.query(models.Product)
        .join(models.ShelfProduct, models.ShelfProduct.product_id == models.Product.id)
        .join(models.Shelf, models.Shelf.id == models.ShelfProduct.shelf_id)
        .join(models.Zone, models.Zone.id == models.Shelf.zone_id)
        .filter(models.Zone.store_id == store_id, models.Product.is_active.is_(True))
        .distinct()
        .order_by(models.Product.name.asc(), models.Product.id.asc())
    )
    total_products = product_query.count()
    products = product_query.limit(limit).all()

    end_day = through_date or date.today()
    start_day = end_day - timedelta(days=days - 1)
    now = models.utc_now()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "UNKNOWN": 3, "LOW": 4}
    items = []
    for product in products:
        records = db.query(models.DailySalesRecord).filter(
            models.DailySalesRecord.store_id == store_id,
            models.DailySalesRecord.product_id == product.id,
            models.DailySalesRecord.source == source,
            models.DailySalesRecord.sales_date >= start_day,
            models.DailySalesRecord.sales_date <= end_day,
        ).all()
        by_day = {}
        for record in records:
            by_day[record.sales_date] = by_day.get(record.sales_date, 0.0) + float(record.quantity)
        missing_days = [
            (start_day + timedelta(days=i)).isoformat()
            for i in range(days) if start_day + timedelta(days=i) not in by_day
        ]

        snapshot = db.query(models.InventorySnapshot).filter(
            models.InventorySnapshot.store_id == store_id,
            models.InventorySnapshot.product_id == product.id,
        ).order_by(
            models.InventorySnapshot.captured_at.desc(),
            models.InventorySnapshot.id.desc(),
        ).first()

        inventory = None
        inventory_status = "MISSING"
        risk = {
            "status": "RISK_UNKNOWN",
            "risk_level": "UNKNOWN",
            "days_of_cover": None,
            "projected_stock_at_receipt": None,
            "safety_stock_gap": None,
            "requires_action": True,
            "explanation": "Não existe snapshot de inventário para este produto.",
        }
        forecast_data = None
        forecast_status = "INSUFFICIENT_HISTORY"
        reason = "INCOMPLETE_SALES_HISTORY" if missing_days else None

        if snapshot is not None:
            captured = snapshot.captured_at
            if captured.tzinfo is None:
                captured = captured.replace(tzinfo=timezone.utc)
            age = max(0.0, (now - captured).total_seconds() / 60)
            inventory = {
                "snapshot_id": snapshot.id,
                "source": snapshot.source,
                "available_quantity": float(snapshot.available_quantity),
                "captured_at": snapshot.captured_at,
                "age_minutes": round(age, 2),
            }
            if age > max_inventory_age_minutes:
                inventory_status = "STALE"
                reason = "STALE_INVENTORY"
                risk["explanation"] = "O snapshot de inventário está desatualizado."
            else:
                inventory_status = "FRESH"

        if not missing_days:
            try:
                forecast = forecast_demand(DemandForecastInput(
                    daily_sales=[by_day[start_day + timedelta(days=i)] for i in range(days)],
                    lead_time_days=lead_time_days,
                    target_cover_days=target_cover_days,
                    recent_window_days=days,
                    minimum_history_days=7,
                ))
                forecast_status = forecast.status
                forecast_data = {
                    "average_daily_demand": forecast.average_daily_demand,
                    "expected_lead_time_demand": forecast.expected_lead_time_demand,
                    "safety_stock": forecast.safety_stock,
                    "reorder_point": forecast.reorder_point,
                    "target_stock": forecast.target_stock,
                }
                if inventory_status == "FRESH":
                    assessed = assess_stockout_risk(StockoutRiskInput(
                        available_quantity=float(snapshot.available_quantity),
                        average_daily_demand=forecast.average_daily_demand,
                        lead_time_days=lead_time_days,
                        safety_stock=forecast.safety_stock,
                        forecast_status=forecast.status,
                    ))
                    risk = {
                        "status": assessed.status,
                        "risk_level": assessed.risk_level,
                        "days_of_cover": assessed.days_of_cover,
                        "projected_stock_at_receipt": assessed.projected_stock_at_receipt,
                        "safety_stock_gap": assessed.safety_stock_gap,
                        "requires_action": assessed.requires_action,
                        "explanation": assessed.explanation,
                    }
                    reason = None
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        open_task_count = db.query(func.count(models.ReplenishmentTask.id)).filter(
            models.ReplenishmentTask.store_id == store_id,
            models.ReplenishmentTask.product_id == product.id,
            models.ReplenishmentTask.status.in_(["PENDING", "ASSIGNED", "IN_PROGRESS"]),
        ).scalar() or 0

        shelf_links = (
            db.query(models.ShelfProduct, models.Shelf, models.Zone)
            .join(models.Shelf, models.Shelf.id == models.ShelfProduct.shelf_id)
            .join(models.Zone, models.Zone.id == models.Shelf.zone_id)
            .filter(models.ShelfProduct.product_id == product.id, models.Zone.store_id == store_id)
            .all()
        )
        items.append({
            "product_id": product.id,
            "sku": product.sku,
            "product_name": product.name,
            "brand": product.brand,
            "shelf_count": len(shelf_links),
            "shelves": [
                {
                    "shelf_id": shelf.id,
                    "shelf_code": shelf.code,
                    "zone_id": zone.id,
                    "zone_name": zone.name,
                    "target_quantity": link.target_quantity,
                    "min_display_quantity": link.min_display_quantity,
                }
                for link, shelf, zone in shelf_links
            ],
            "inventory_status": inventory_status,
            "inventory": inventory,
            "forecast_status": forecast_status,
            "forecast": forecast_data,
            "missing_sales_days": missing_days,
            "reason": reason,
            "risk": risk,
            "open_task_count": int(open_task_count),
        })

    items.sort(key=lambda item: (
        severity_order.get(item["risk"]["risk_level"], 3),
        -(item["risk"]["safety_stock_gap"] or 0),
        item["product_name"].casefold(),
    ))
    counts = {level: 0 for level in severity_order}
    for item in items:
        counts[item["risk"]["risk_level"]] += 1

    return {
        "store_id": store_id,
        "source": source,
        "period_start": start_day,
        "period_end": end_day,
        "total_products": total_products,
        "returned_products": len(items),
        "limit": limit,
        "risk_counts": counts,
        "items": items,
        "policy": "Read-only portfolio. No replenishment task, purchase order or inventory movement is created.",
    }


@app.post("/api/v1/inventory/snapshots", response_model=InventorySnapshotRead, status_code=201, tags=["inventory"])
def create_inventory_snapshot(payload: InventorySnapshotCreate, request: Request, db: Session = Depends(get_db)):
    _enforce_store_scope(_request_user(db, request), payload.store_id)
    if not db.get(models.Store, payload.store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    if not db.get(models.Product, payload.product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    data = payload.model_dump()
    if data["captured_at"] is None:
        data["captured_at"] = models.utc_now()
    elif data["captured_at"].tzinfo is None:
        data["captured_at"] = data["captured_at"].replace(tzinfo=timezone.utc)
    item = models.InventorySnapshot(**data)
    db.add(item)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Inventory source reference already exists") from exc
    db.refresh(item)
    return item


@app.get("/api/v1/inventory/snapshots", response_model=list[InventorySnapshotRead], tags=["inventory"])
def list_inventory_snapshots(
    store_id: int | None = None,
    product_id: int | None = None,
    limit: int = 100,
    request: Request = None,
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    query = db.query(models.InventorySnapshot)
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN":
        _enforce_store_scope(actor, store_id if store_id is not None else actor.store_id)
        query = query.filter(models.InventorySnapshot.store_id == actor.store_id)
    if store_id is not None:
        query = query.filter(models.InventorySnapshot.store_id == store_id)
    if product_id is not None:
        query = query.filter(models.InventorySnapshot.product_id == product_id)
    return query.order_by(models.InventorySnapshot.captured_at.desc(), models.InventorySnapshot.id.desc()).limit(limit).all()


@app.get("/api/v1/inventory/latest", response_model=InventorySnapshotRead, tags=["inventory"])
def get_latest_inventory_snapshot(
    store_id: int,
    product_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    _enforce_store_scope(_request_user(db, request), store_id)
    item = db.query(models.InventorySnapshot).filter(
        models.InventorySnapshot.store_id == store_id,
        models.InventorySnapshot.product_id == product_id,
    ).order_by(models.InventorySnapshot.captured_at.desc(), models.InventorySnapshot.id.desc()).first()
    if item is None:
        raise HTTPException(status_code=404, detail="No inventory snapshot found for this store and product")
    return item



@app.get(
    "/api/v1/replenishment/recommendations",
    response_model=list[ReplenishmentRecommendationRead],
    tags=["replenishment"],
)
def list_replenishment_recommendations(
    store_id: int,
    product_id: int | None = None,
    stale_after_minutes: int = 120,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Combine shelf observations with the latest backroom inventory snapshot.

    A visual status is not a unit count, so this endpoint never invents an
    exact replenishment quantity.
    """
    if stale_after_minutes < 1 or stale_after_minutes > 10080:
        raise HTTPException(status_code=422, detail="stale_after_minutes must be between 1 and 10080")
    _enforce_store_scope(_request_user(db, request), store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")

    links = (
        db.query(models.ShelfProduct)
        .join(models.Shelf, models.ShelfProduct.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Zone.store_id == store_id)
    )
    if product_id is not None:
        links = links.filter(models.ShelfProduct.product_id == product_id)

    now = models.utc_now()
    recommendations = []
    for link in links.order_by(models.ShelfProduct.shelf_id, models.ShelfProduct.product_id).all():
        shelf = db.get(models.Shelf, link.shelf_id)
        product = db.get(models.Product, link.product_id)
        observation = (
            db.query(models.Observation)
            .filter(models.Observation.shelf_id == link.shelf_id)
            .order_by(models.Observation.observed_at.desc(), models.Observation.id.desc())
            .first()
        )
        inventory = (
            db.query(models.InventorySnapshot)
            .filter(
                models.InventorySnapshot.store_id == store_id,
                models.InventorySnapshot.product_id == link.product_id,
            )
            .order_by(models.InventorySnapshot.captured_at.desc(), models.InventorySnapshot.id.desc())
            .first()
        )

        status = "NO_ACTION"
        explanation = "A observação mais recente não indica baixa disponibilidade."
        available = float(inventory.available_quantity) if inventory is not None else None
        suggested_quantity = None
        observed_shelf_quantity = (
            float(observation.observed_quantity)
            if observation is not None and observation.observed_quantity is not None
            else None
        )

        if observation is None:
            status = "STALE_OBSERVATION"
            explanation = "Ainda não existe observação registada para esta prateleira."
        else:
            observed_at = observation.observed_at
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            observation_age_minutes = max(0.0, (now - observed_at).total_seconds() / 60)
            if observation_age_minutes > stale_after_minutes:
                status = "STALE_OBSERVATION"
                explanation = "A observação é demasiado antiga para suportar uma tarefa de reposição."
            elif observation.status in ("LOW_STOCK", "EMPTY"):
                if observation.confidence is None or observation.confidence < 0.6:
                    status = "LOW_CONFIDENCE"
                    explanation = "A deteção não tem confiança suficiente (mínimo 0,60); requer confirmação humana."
                elif inventory is None:
                    status = "INVENTORY_UNKNOWN"
                    explanation = "Não existe snapshot de inventário; verificar stock antes de repor."
                elif available <= 0:
                    status = "BACKROOM_OUT_OF_STOCK"
                    explanation = "A prateleira necessita de atenção, mas o stock disponível na retaguarda é zero."
                elif observed_shelf_quantity is None:
                    status = "NEEDS_REPLENISHMENT"
                    explanation = "A prateleira apresenta baixa disponibilidade e existe stock na retaguarda; a quantidade exata ainda não foi medida."
                else:
                    decision = suggest_shelf_refill(ShelfRefillInput(
                        shelf_quantity=observed_shelf_quantity,
                        target_quantity=link.target_quantity,
                        min_display_quantity=link.min_display_quantity,
                        backroom_available_quantity=available,
                        observation_confidence=observation.confidence,
                        observation_age_minutes=observation_age_minutes,
                        max_observation_age_minutes=stale_after_minutes,
                    ))
                    status = decision.status
                    suggested_quantity = decision.suggested_quantity
                    explanation = decision.explanation
            elif observation.status == "UNKNOWN":
                status = "LOW_CONFIDENCE"
                explanation = "O estado visual é desconhecido e deve ser confirmado."

        recommendations.append({
            "store_id": store_id,
            "shelf_id": shelf.id,
            "shelf_code": shelf.code,
            "zone_id": shelf.zone_id,
            "zone_name": shelf.zone.name,
            "product_id": product.id,
            "product_name": product.name,
            "sku": product.sku,
            "observation_status": observation.status if observation else None,
            "observation_confidence": observation.confidence if observation else None,
            "observed_shelf_quantity": observed_shelf_quantity,
            "observed_at": observation.observed_at if observation else None,
            "inventory_available_quantity": available,
            "inventory_captured_at": inventory.captured_at if inventory else None,
            "recommendation_status": status,
            "suggested_quantity": suggested_quantity,
            "explanation": explanation,
        })
    return recommendations



@app.get("/api/v1/replenishment/plan", tags=["replenishment"])
def get_replenishment_plan(
    store_id: int,
    stale_after_minutes: int = 120,
    limit: int = 200,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Build a read-only, zone-grouped work queue from current shelf recommendations."""
    if stale_after_minutes < 1 or stale_after_minutes > 10080:
        raise HTTPException(status_code=422, detail="stale_after_minutes must be between 1 and 10080")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    _enforce_store_scope(_request_user(db, request), store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")

    recommendations = list_replenishment_recommendations(
        store_id=store_id, stale_after_minutes=stale_after_minutes, request=request, db=db,
    )
    active_tasks = db.query(models.ReplenishmentTask).filter(
        models.ReplenishmentTask.store_id == store_id,
        models.ReplenishmentTask.status.in_(("PENDING", "ASSIGNED", "IN_PROGRESS")),
    ).all()
    active_keys = {(task.shelf_id, task.product_id) for task in active_tasks}
    plan = build_replenishment_plan(recommendations, active_keys=active_keys, limit=limit)
    return {
        "store_id": store_id,
        "generated_at": models.utc_now(),
        "read_only": True,
        "total_candidates": plan.total_candidates,
        "returned_candidates": plan.returned_candidates,
        "groups": [
            {"zone_id": group.zone_id, "zone_name": group.zone_name, "tasks": list(group.items)}
            for group in plan.groups
        ],
        "excluded": plan.excluded,
        "policy": "Proposta de organização; não cria nem atribui tarefas e não substitui validação humana.",
    }


@app.post("/api/v1/tasks", response_model=ReplenishmentTaskRead, status_code=201, tags=["tasks"])
def create_replenishment_task(payload: ReplenishmentTaskCreate, request: Request, db: Session = Depends(get_db)):
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN" and actor.store_id != payload.store_id:
        raise HTTPException(status_code=403, detail="Access to this store is not allowed")
    if not db.get(models.Store, payload.store_id):
        raise HTTPException(status_code=404, detail="Store not found")
    shelf = (
        db.query(models.Shelf)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .filter(models.Shelf.id == payload.shelf_id, models.Zone.store_id == payload.store_id)
        .first()
    )
    if shelf is None:
        raise HTTPException(status_code=404, detail="Shelf not found in this store")
    if not db.get(models.Product, payload.product_id):
        raise HTTPException(status_code=404, detail="Product not found")
    assignment = db.query(models.ShelfProduct).filter_by(
        shelf_id=payload.shelf_id, product_id=payload.product_id
    ).first()
    if assignment is None:
        raise HTTPException(status_code=409, detail="Product is not assigned to this shelf")
    active_task = db.query(models.ReplenishmentTask).filter(
        models.ReplenishmentTask.store_id == payload.store_id,
        models.ReplenishmentTask.shelf_id == payload.shelf_id,
        models.ReplenishmentTask.product_id == payload.product_id,
        models.ReplenishmentTask.status.in_(("PENDING", "ASSIGNED", "IN_PROGRESS")),
    ).first()
    if active_task is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "ACTIVE_TASK_EXISTS", "task_id": active_task.id,
                    "status": active_task.status,
                    "message": "Já existe uma tarefa ativa para este produto nesta prateleira."},
        )
    data = payload.model_dump()
    assigned_user_id = data.pop("assigned_user_id", None)
    if assigned_user_id is not None:
        assignee = db.get(models.User, assigned_user_id)
        if assignee is None or not assignee.is_active or assignee.store_id != payload.store_id:
            raise HTTPException(status_code=422, detail="Assigned user must be active and belong to this store")
        data["assigned_to"] = assignee.full_name
    data["assigned_user_id"] = assigned_user_id
    data["status"] = "ASSIGNED" if (data["assigned_to"] or assigned_user_id) else "PENDING"
    item = models.ReplenishmentTask(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@app.post(
    "/api/v1/tasks/from-recommendation",
    response_model=ReplenishmentTaskRead,
    status_code=201,
    tags=["tasks"],
)
def create_task_from_recommendation(
    payload: ReplenishmentTaskCreate,
    request: Request,
    stale_after_minutes: int = 120,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN" and actor.store_id != payload.store_id:
        raise HTTPException(status_code=403, detail="Access to this store is not allowed")
    recommendations = list_replenishment_recommendations(
        store_id=payload.store_id,
        product_id=payload.product_id,
        stale_after_minutes=stale_after_minutes,
        db=db,
    )
    recommendation = next(
        (
            item for item in recommendations
            if item["shelf_id"] == payload.shelf_id
            and item["product_id"] == payload.product_id
        ),
        None,
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Product is not assigned to a shelf in this store")
    if recommendation["recommendation_status"] != "NEEDS_REPLENISHMENT":
        raise HTTPException(
            status_code=409,
            detail=f"Cannot create replenishment task: recommendation status is {recommendation['recommendation_status']}",
        )

    active_task = db.query(models.ReplenishmentTask).filter(
        models.ReplenishmentTask.store_id == payload.store_id,
        models.ReplenishmentTask.shelf_id == payload.shelf_id,
        models.ReplenishmentTask.product_id == payload.product_id,
        models.ReplenishmentTask.status.in_(("PENDING", "ASSIGNED", "IN_PROGRESS")),
    ).first()
    if active_task is not None:
        raise HTTPException(status_code=409, detail="An active replenishment task already exists")

    data = payload.model_dump()
    suggested_quantity = recommendation["suggested_quantity"]
    available_quantity = recommendation["inventory_available_quantity"]
    if suggested_quantity is None and data["requested_quantity"] is None:
        raise HTTPException(
            status_code=409,
            detail={"code": "QUANTITY_REQUIRES_CONFIRMATION",
                    "message": "A recomendação não tem uma quantidade observada fiável. Confirme a quantidade antes de criar a tarefa."},
        )
    if data["requested_quantity"] is None:
        data["requested_quantity"] = suggested_quantity
    if available_quantity is None or data["requested_quantity"] > available_quantity:
        raise HTTPException(
            status_code=409,
            detail={"code": "INSUFFICIENT_BACKROOM_STOCK",
                    "available_quantity": available_quantity,
                    "requested_quantity": data["requested_quantity"],
                    "message": "A quantidade solicitada não pode exceder o stock disponível na retaguarda."},
        )
    assigned_user_id = data.pop("assigned_user_id", None)
    if assigned_user_id is not None:
        assignee = db.get(models.User, assigned_user_id)
        if assignee is None or not assignee.is_active or assignee.store_id != payload.store_id:
            raise HTTPException(status_code=422, detail="Assigned user must be active and belong to this store")
        data["assigned_to"] = assignee.full_name
    data["assigned_user_id"] = assigned_user_id
    data["status"] = "ASSIGNED" if (data["assigned_to"] or assigned_user_id) else "PENDING"
    item = models.ReplenishmentTask(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item



@app.get("/api/v1/tasks", response_model=list[ReplenishmentTaskRead], tags=["tasks"])
def list_replenishment_tasks(
    store_id: int | None = None,
    status: str | None = None,
    assigned_to: str | None = None,
    limit: int = 100,
    request: Request = None,
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    actor = _request_user(db, request)
    query = db.query(models.ReplenishmentTask)
    if actor is not None and actor.role == "EMPLOYEE":
        query = query.filter(models.ReplenishmentTask.assigned_user_id == actor.id)
    elif actor is not None and actor.role != "ADMIN":
        query = query.filter(models.ReplenishmentTask.store_id == actor.store_id)
    if store_id is not None:
        query = query.filter(models.ReplenishmentTask.store_id == store_id)
    if status is not None:
        if status not in {"PENDING", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}:
            raise HTTPException(status_code=422, detail="Invalid task status")
        query = query.filter(models.ReplenishmentTask.status == status)
    if assigned_to is not None:
        query = query.filter(models.ReplenishmentTask.assigned_to == assigned_to)
    return query.order_by(models.ReplenishmentTask.created_at.desc(), models.ReplenishmentTask.id.desc()).limit(limit).all()


@app.get("/api/v1/replenishment/workload", tags=["replenishment"])
def get_replenishment_workload(
    store_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Return workload indicators for supervisors; never auto-assign tasks."""
    actor = _request_user(db, request)
    if actor is not None and actor.role == "EMPLOYEE":
        raise HTTPException(status_code=403, detail="Only administrators and supervisors can view team workload")
    _enforce_store_scope(actor, store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")

    users = db.query(models.User).filter(
        models.User.store_id == store_id,
        models.User.role == "EMPLOYEE",
        models.User.is_active.is_(True),
    ).order_by(models.User.full_name.asc(), models.User.id.asc()).all()
    tasks = (
        db.query(models.ReplenishmentTask, models.Zone.name)
        .outerjoin(models.Shelf, models.ReplenishmentTask.shelf_id == models.Shelf.id)
        .outerjoin(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .filter(models.ReplenishmentTask.store_id == store_id)
        .all()
    )
    summary = summarize_workload(
        [{"id": user.id, "name": user.full_name} for user in users],
        [{
            "id": task.id, "assigned_user_id": task.assigned_user_id,
            "status": task.status, "started_at": task.started_at,
            "completed_at": task.completed_at, "zone_name": zone_name,
            "priority": task.priority,
        } for task, zone_name in tasks],
    )
    return {
        "store_id": store_id,
        "generated_at": models.utc_now(),
        "employees": list(summary.employees),
        "unassigned_active_tasks": summary.unassigned_active_tasks,
        "completed_tasks_with_duration": summary.completed_tasks_with_duration,
        "average_completion_minutes": summary.average_completion_minutes,
        "duration_by_zone": list(summary.duration_by_zone),
        "duration_by_priority": list(summary.duration_by_priority),
        "duration_benchmark_minimum_sample_size": 5,
        "policy": "Indicadores históricos e de carga registada; médias segmentadas só são publicadas com pelo menos cinco tarefas válidas por grupo. Não representam disponibilidade, turno ou capacidade real.",
    }


@app.patch("/api/v1/tasks/{task_id}/status", response_model=ReplenishmentTaskRead, tags=["tasks"])
def update_replenishment_task_status(
    task_id: int,
    payload: ReplenishmentTaskStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    task = db.get(models.ReplenishmentTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN" and task.store_id != actor.store_id:
        raise HTTPException(status_code=403, detail="Access to this task is not allowed")
    if actor is not None and actor.role == "EMPLOYEE":
        if task.assigned_user_id != actor.id:
            raise HTTPException(status_code=403, detail="Employees can only update tasks assigned to them")
        if payload.status not in {"IN_PROGRESS", "COMPLETED"}:
            raise HTTPException(status_code=403, detail="Employees cannot assign or cancel tasks")
        if payload.assigned_to is not None or payload.assigned_user_id is not None:
            raise HTTPException(status_code=403, detail="Employees cannot change task assignees")

    allowed = {
        "PENDING": {"ASSIGNED", "CANCELLED"},
        "ASSIGNED": {"IN_PROGRESS", "CANCELLED"},
        "IN_PROGRESS": {"COMPLETED", "CANCELLED"},
        "COMPLETED": set(),
        "CANCELLED": set(),
    }
    if payload.status not in allowed[task.status]:
        raise HTTPException(
            status_code=409,
            detail=f"Transition from {task.status} to {payload.status} is not allowed",
        )
    if payload.status == "ASSIGNED":
        assignee = payload.assigned_to or task.assigned_to
        if payload.assigned_user_id is not None:
            user = db.get(models.User, payload.assigned_user_id)
            if user is None or not user.is_active or user.store_id != task.store_id:
                raise HTTPException(status_code=422, detail="Assigned user must be active and belong to this store")
            task.assigned_user_id = user.id
            assignee = user.full_name
        if not assignee:
            raise HTTPException(status_code=422, detail="assigned_to is required to assign a task")
        task.assigned_to = assignee
    elif payload.assigned_to is not None or payload.assigned_user_id is not None:
        raise HTTPException(status_code=422, detail="Assignee can only be set when assigning a task")

    now = models.utc_now()
    task.status = payload.status
    task.updated_at = now
    if payload.status == "IN_PROGRESS":
        task.started_at = now
    elif payload.status == "COMPLETED":
        task.completed_at = now
    db.commit()
    db.refresh(task)
    return task


@app.post("/api/v1/auth/bootstrap", response_model=TokenRead, status_code=201, tags=["authentication"])
def bootstrap_first_admin(
    payload: BootstrapAdminCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Create the first administrator exactly once using a private bootstrap key."""
    supplied_key = request.headers.get("X-Bootstrap-Key", "")
    if not settings.bootstrap_admin_key or supplied_key != settings.bootstrap_admin_key:
        raise HTTPException(status_code=403, detail="Invalid or unconfigured bootstrap key")
    if db.query(models.User).count() > 0:
        raise HTTPException(status_code=409, detail="Administrator bootstrap has already been completed")
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email address is required")
    user = models.User(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role="ADMIN",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token, expires_in = create_access_token(user_id=user.id, role=user.role)
    return {"access_token": token, "expires_in": expires_in, "user": user}


@app.post("/api/v1/auth/login", response_model=TokenRead, tags=["authentication"])
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.query(models.User).filter(func.lower(models.User.email) == email).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=401,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token, expires_in = create_access_token(user_id=user.id, role=user.role)
    return {"access_token": token, "expires_in": expires_in, "user": user}


@app.get("/api/v1/auth/me", response_model=UserRead, tags=["authentication"])
def current_user(request: Request, db: Session = Depends(get_db)):
    user = db.get(models.User, request.state.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User account is inactive or unavailable")
    return user


@app.post("/api/v1/auth/users", response_model=UserRead, status_code=201, tags=["authentication"])
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="A valid email address is required")
    if payload.role != "ADMIN" and payload.store_id is None:
        raise HTTPException(status_code=422, detail="A store_id is required for supervisors and employees")
    if payload.store_id is not None and db.get(models.Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if db.query(models.User).filter(func.lower(models.User.email) == email).first():
        raise HTTPException(status_code=409, detail="Email address already exists")
    user = models.User(
        email=email,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        store_id=payload.store_id,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.get("/api/v1/auth/users", response_model=list[UserRead], tags=["authentication"])
def list_users(limit: int = 100, db: Session = Depends(get_db)):
    return db.query(models.User).order_by(models.User.id).limit(max(1, min(limit, 500))).all()


@app.get("/api/v1/dashboard/summary", tags=["dashboard"])
def dashboard_summary(
    request: Request,
    store_id: int | None = None,
    db: Session = Depends(get_db),
):
    """Return operational KPIs scoped to the authenticated user's store."""
    user = db.get(models.User, request.state.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Authenticated user not found")
    if user.role == "ADMIN":
        if store_id is None:
            task_query = db.query(models.ReplenishmentTask)
            observation_query = (
                db.query(models.Observation)
                .join(models.Shelf, models.Observation.shelf_id == models.Shelf.id)
                .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
            )
        else:
            task_query = db.query(models.ReplenishmentTask).filter(models.ReplenishmentTask.store_id == store_id)
            observation_query = (
                db.query(models.Observation)
                .join(models.Shelf, models.Observation.shelf_id == models.Shelf.id)
                .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
                .filter(models.Zone.store_id == store_id)
            )
    else:
        if user.store_id is None:
            raise HTTPException(status_code=403, detail="User is not associated with a store")
        if store_id is not None and store_id != user.store_id:
            raise HTTPException(status_code=403, detail="Access to this store is not allowed")
        task_query = db.query(models.ReplenishmentTask).filter(models.ReplenishmentTask.store_id == user.store_id)
        observation_query = (
            db.query(models.Observation)
            .join(models.Shelf, models.Observation.shelf_id == models.Shelf.id)
            .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
            .filter(models.Zone.store_id == user.store_id)
        )
    if user.role == "EMPLOYEE":
        task_query = task_query.filter(models.ReplenishmentTask.assigned_user_id == user.id)
    task_counts = {
        status.lower(): task_query.filter(models.ReplenishmentTask.status == status).count()
        for status in ("PENDING", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    }
    observation_counts = {
        status.lower(): observation_query.filter(models.Observation.status == status).count()
        for status in ("LOW_STOCK", "EMPTY", "UNKNOWN", "OCCLUDED")
    }
    return {
        "store_id": user.store_id if user.role != "ADMIN" else store_id,
        "role": user.role,
        "tasks": task_counts,
        "observations": observation_counts,
        "active_tasks": task_counts["pending"] + task_counts["assigned"] + task_counts["in_progress"],
        "shelves_requiring_attention": observation_counts["low_stock"] + observation_counts["empty"],
        "note": "Counts are based on recorded observations; they are not a live computer-vision feed.",
    }
