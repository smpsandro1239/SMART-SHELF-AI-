from datetime import date, datetime, timedelta, timezone
from io import BytesIO
import warnings
from decimal import Decimal
import math
from pathlib import Path
from uuid import uuid4
import hashlib

from PIL import Image, UnidentifiedImageError

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.exceptions import RequestValidationError
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
from app.operational_decision_engine import evaluate_shelf_decision
from app.security import hash_password, verify_password, create_access_token, decode_access_token
from app.product_text import (
    CatalogueProduct, normalize_product_text, rank_product_catalogue_candidates,
)
from app.replenishment_policy import ShelfRefillInput, suggest_shelf_refill
from app.demand_forecasting import DemandForecastInput, forecast_demand
from app.stockout_risk import StockoutRiskInput, assess_stockout_risk
from app.replenishment_planning import build_replenishment_plan
from app.replenishment_risk_bridge import enrich_replenishment_with_stockout_risk
from app.replenishment_workload import summarize_workload
from app.replenishment_effort import enrich_plan_with_effort_estimates
from app.warehouse_pick_planning import build_warehouse_pick_plan
from app.warehouse_slotting import recommend_warehouse_slotting, recommend_physical_slot
from app.packaging_units import calculate_replenishment_packs
from app.pallet_rotation import evaluate_pallet_rotation, PalletRotationInputError
from app.pallet_portfolio import (
    allocate_ready_replacements, build_pallet_portfolio_plan, PalletPortfolioInputError,
)
from app.pallet_rotation_forecast_bridge import enrich_pallet_candidates_with_hourly_profiles
from app.pallet_rotation_windows import recommend_low_traffic_window
from app.hourly_patterns import build_weekday_hour_profile
from app.hourly_demand_forecast import forecast_hourly_demand
from app.traffic_peak_detection import detect_weekday_hour_traffic_peaks
from app.sku_review_evaluation import build_reviewed_prediction_report
from app.sales_import import parse_daily_sales_csv
from app.sales_import_hourly import parse_hourly_sales_csv, parse_hourly_traffic_csv
from app.schemas import (
    ObservationCreate, ObservationRead, ShelfCreate, ShelfRead,
    StoreCreate, StoreRead, ZoneCreate, ZoneRead,
    ProductCreate, ProductRead, ShelfProductCreate, ShelfProductRead,
    InventorySnapshotCreate, InventorySnapshotRead, InventoryReconciliationCreate, InventoryMovementRead, InventoryFreshnessPolicyUpsert, InventoryFreshnessPolicyRead, ReplenishmentRecommendationRead,
    DailySalesRecordCreate, DailySalesRecordRead, SalesSource,
    HourlySalesRecordCreate, HourlySalesRecordRead, HourlyStoreTrafficRecordCreate, HourlyStoreTrafficRecordRead,
    HourlySalesBatchCreate, HourlyStoreTrafficBatchCreate,
    ReplenishmentTaskCreate, ReplenishmentTaskStatusUpdate, ReplenishmentTaskRead, ReplenishmentTaskEventRead,
    BootstrapAdminCreate, LoginRequest, TokenRead, UserRead, UserCreate, ShelfImageRead,
    ShelfImageDetectionRead, ProductEmbeddingExemplarCreate,
    ProductEmbeddingExemplarReview, ProductEmbeddingExemplarRead,
    DetectionSkuReviewCreate, DetectionSkuReviewRead,
    ShelfImageOCRRunCreate, ShelfImageOCRRunRead, ShelfImageOCREvidenceRead,
    ShelfImageOCRMatchRead,
    ShelfImageFusedEvidenceRead, ShelfImageRetentionRequest, ShelfImageRetentionEventRead,
    ShelfImageReviewQueueItem, ShelfImageTrainingCandidateRead, CaptureSessionCreate, CaptureSessionRead,
    WarehouseLocationCreate, WarehouseProductProfileCreate, WarehousePlacementCreate,
    ProductPackagingLevelCreate, StorePalletCreate, StorePalletRead,
    PalletRotationPolicyCreate, PalletRotationPolicyRead, PalletRotationPolicyUpdate, PalletRotationEventRead, PalletLifecycleUpdate, PalletRotationSimulationRequest,
)

app = FastAPI(title=settings.app_name, version="0.2.0", description="Operational API for SMART SHELF AI.")


def _json_safe_validation_value(value):
    """Convert non-JSON values in validation errors into safe display values."""
    if isinstance(value, float) and not math.isfinite(value):
        return repr(value)
    if isinstance(value, BaseException):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe_validation_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_validation_value(item) for item in value]
    return value


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    """Keep invalid numeric input as a normal 422 response, even for NaN/Infinity."""
    return JSONResponse(
        status_code=422,
        content={"detail": _json_safe_validation_value(exc.errors())},
    )


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
            (method == "POST" and path == "/api/v1/tasks/from-operational-decision")
            or (method == "POST" and (path in {"/api/v1/sales/daily", "/api/v1/sales/import-csv", "/api/v1/warehouse/locations", "/api/v1/warehouse/placements", "/api/v1/warehouse/pallets", "/api/v1/warehouse/pallet-rotation/policies", "/api/v1/warehouse/pallet-rotation/simulate", "/api/v1/sales/hourly", "/api/v1/sales/traffic/hourly", "/api/v1/sales/hourly/batch", "/api/v1/sales/traffic/hourly/batch", "/api/v1/sales/hourly/import-csv", "/api/v1/sales/traffic/hourly/import-csv"} or (path.startswith("/api/v1/warehouse/pallets/") and path.endswith("/events"))))
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


def _require_active_shelf_image(image: models.ShelfImage) -> None:
    """Prevent restricted or purged captures from being read or processed."""
    if image.retention_status != "ACTIVE":
        raise HTTPException(status_code=410, detail="Shelf image is not available under its retention state")


def _resolve_shelf_image_storage_path(storage_path: str, store_id: int) -> Path:
    """Resolve an image path and ensure it remains inside its configured store directory."""
    root = Path(settings.image_storage_path).resolve()
    store_root = (root / str(store_id)).resolve()
    try:
        store_root.relative_to(root)
        candidate = Path(storage_path)
        resolved = candidate.resolve()
        resolved.relative_to(store_root)
    except (OSError, RuntimeError, ValueError):
        raise HTTPException(status_code=404, detail="Stored image file is unavailable")
    if candidate.is_symlink() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Stored image file is unavailable")
    return resolved


def _enforce_store_scope(actor: models.User | None, store_id: int) -> None:
    if actor is not None and actor.role != "ADMIN" and actor.store_id != store_id:
        raise HTTPException(status_code=403, detail="Access to this store is not allowed")


def _lock_store_for_task_creation(db: Session, store_id: int) -> None:
    """Serialize task creation per store on databases supporting row-level locks."""
    store = (
        db.query(models.Store)
        .filter(models.Store.id == store_id)
        .with_for_update()
        .first()
    )
    if store is None:
        raise HTTPException(status_code=404, detail="Store not found")


def _record_task_event(db: Session, task: models.ReplenishmentTask, event_type: str, actor: models.User | None, *, from_status: str | None = None, to_status: str | None = None, actual_quantity: float | None = None, reason: str | None = None) -> None:
    db.add(models.ReplenishmentTaskEvent(
        task_id=task.id, event_type=event_type, from_status=from_status,
        to_status=to_status, actor_user_id=actor.id if actor is not None else None,
        actual_quantity=actual_quantity, reason=reason, created_at=models.utc_now(),
    ))


def _persist_new_task(
    db: Session,
    task: models.ReplenishmentTask,
    actor: models.User | None,
    *,
    creation_reason: str,
    approval_quantity: float | None = None,
    approval_reason: str | None = None,
) -> models.ReplenishmentTask:
    """Persist a task and its audit events atomically.

    The partial unique index is the final concurrency guard. The store row lock
    remains an optimization that serializes task creation on PostgreSQL.
    """
    try:
        db.add(task)
        db.flush()
        _record_task_event(
            db, task, "CREATED", actor, to_status=task.status,
            reason=creation_reason,
        )
        if approval_quantity is not None:
            _record_task_event(
                db, task, "APPROVED", actor, to_status=task.status,
                actual_quantity=approval_quantity, reason=approval_reason,
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        active_task = db.query(models.ReplenishmentTask).filter(
            models.ReplenishmentTask.store_id == task.store_id,
            models.ReplenishmentTask.shelf_id == task.shelf_id,
            models.ReplenishmentTask.product_id == task.product_id,
            models.ReplenishmentTask.status.in_(("PENDING", "ASSIGNED", "IN_PROGRESS")),
        ).first()
        if active_task is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ACTIVE_TASK_EXISTS",
                    "task_id": active_task.id,
                    "status": active_task.status,
                    "message": "Já existe uma tarefa ativa para este produto nesta prateleira.",
                },
            ) from exc
        raise
    db.refresh(task)
    return task


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

    expected_format = {
        "image/jpeg": "JPEG",
        "image/png": "PNG",
        "image/webp": "WEBP",
    }[mime_type]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(content)) as decoded:
                if decoded.format != expected_format:
                    raise ValueError("Decoded image format does not match MIME type")
                width, height = decoded.size
                if width < 1 or height < 1 or width * height > 40_000_000:
                    raise ValueError("Image dimensions exceed the permitted pixel limit")
                decoded.verify()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(status_code=415, detail="Uploaded file is not a valid supported image")

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
        original_filename=(Path((image.filename or "capture").replace("\\", "/")).name[:255]),
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


@app.post(
    "/api/v1/shelf-images/{image_id}/retention/restrict",
    response_model=ShelfImageRead,
    tags=["computer-vision"],
)
def restrict_shelf_image(image_id: int, payload: ShelfImageRetentionRequest, request: Request, db: Session = Depends(get_db)):
    """Restrict access without deleting image data or its human-review evidence."""
    actor = _request_user(db, request)
    if actor is not None and actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="Supervisor role required")
    item = db.query(models.ShelfImage).filter(models.ShelfImage.id == image_id).with_for_update().first()
    if item is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    _enforce_store_scope(actor, _shelf_image_store_id(db, image_id))
    if item.retention_status == "PURGED":
        raise HTTPException(status_code=409, detail="Purged image cannot be restricted")
    if item.retention_status == "ACTIVE":
        item.retention_status = "RESTRICTED"
        item.retention_requested_at = models.utc_now()
        item.retention_requested_by_user_id = actor.id if actor else None
        item.retention_reason = payload.reason.strip()
        db.add(models.ShelfImageRetentionEvent(
            shelf_image_id=item.id, event_type="RESTRICTED", from_status="ACTIVE",
            to_status="RESTRICTED", actor_user_id=actor.id if actor else None,
            reason=payload.reason.strip(),
        ))
        db.commit()
        db.refresh(item)
    return item


@app.post(
    "/api/v1/shelf-images/{image_id}/retention/restore",
    response_model=ShelfImageRead,
    tags=["computer-vision"],
)
def restore_shelf_image(image_id: int, payload: ShelfImageRetentionRequest, request: Request, db: Session = Depends(get_db)):
    """Restore access only through an administrator decision."""
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN":
        raise HTTPException(status_code=403, detail="Administrator role required to restore an image")
    item = db.query(models.ShelfImage).filter(models.ShelfImage.id == image_id).with_for_update().first()
    if item is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    _enforce_store_scope(actor, _shelf_image_store_id(db, image_id))
    if item.retention_status != "RESTRICTED":
        raise HTTPException(status_code=409, detail="Only restricted images can be restored")
    item.retention_status = "ACTIVE"
    item.retention_reason = payload.reason.strip()
    db.add(models.ShelfImageRetentionEvent(
        shelf_image_id=item.id, event_type="RESTORED", from_status="RESTRICTED",
        to_status="ACTIVE", actor_user_id=actor.id if actor else None,
        reason=payload.reason.strip(),
    ))
    db.commit()
    db.refresh(item)
    return item


@app.get(
    "/api/v1/shelf-images/{image_id}/retention/events",
    response_model=list[ShelfImageRetentionEventRead],
    tags=["computer-vision"],
)
def list_shelf_image_retention_events(image_id: int, request: Request, db: Session = Depends(get_db)):
    item = db.get(models.ShelfImage, image_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    _enforce_store_scope(_request_user(db, request), _shelf_image_store_id(db, image_id))
    return (
        db.query(models.ShelfImageRetentionEvent)
        .filter(models.ShelfImageRetentionEvent.shelf_image_id == image_id)
        .order_by(models.ShelfImageRetentionEvent.created_at, models.ShelfImageRetentionEvent.id)
        .all()
    )


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
    query = query.filter(models.ShelfImage.retention_status == "ACTIVE")
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
    store_id = _shelf_image_store_id(db, image_id)
    if store_id is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    _require_active_shelf_image(item)
    path = _resolve_shelf_image_storage_path(item.storage_path, store_id)
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
    _require_active_shelf_image(item)
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
    _require_active_shelf_image(image_record)
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
    _require_active_shelf_image(image_record)
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
    _require_active_shelf_image(image_record)
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
    _require_active_shelf_image(image_record)
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
        .filter(models.ShelfImage.retention_status == "ACTIVE")
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
    query = query.filter(models.ShelfImage.retention_status == "ACTIVE")
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
        .filter(models.ShelfImage.retention_status == "ACTIVE")
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
    _require_active_shelf_image(image_record)
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
    _require_active_shelf_image(image_record)
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
    _require_active_shelf_image(image_record)
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
    _require_active_shelf_image(image_record)
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
    _require_active_shelf_image(image_record)
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
    image_record = db.get(models.ShelfImage, detection.shelf_image_id)
    if image_record is None:
        raise HTTPException(status_code=404, detail="Shelf image not found")
    _require_active_shelf_image(image_record)
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
        models.HourlySalesRecord.business_date <= date.today(),
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
        models.HourlyStoreTrafficRecord.business_date <= date.today(),
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


@app.get("/api/v1/forecasting/traffic-peaks", tags=["forecasting"])
def get_store_traffic_peaks(
    store_id: int, days: int = 56, minimum_observed_days: int = 4,
    minimum_baseline_hours: int = 6, peak_ratio: float = 1.5,
    source: SalesSource = "POS", request: Request = None,
    db: Session = Depends(get_db),
):
    """Classify historical high-traffic weekday/hour cells; read-only."""
    if not 14 <= days <= 180:
        raise HTTPException(status_code=422, detail="days must be between 14 and 180")
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    start_date = date.today() - timedelta(days=days - 1)
    records = db.query(models.HourlyStoreTrafficRecord).filter(
        models.HourlyStoreTrafficRecord.store_id == store_id,
        models.HourlyStoreTrafficRecord.source == source,
        models.HourlyStoreTrafficRecord.business_date >= start_date,
        models.HourlyStoreTrafficRecord.business_date <= date.today(),
    ).all()
    try:
        result = detect_weekday_hour_traffic_peaks(
            records, minimum_observed_days=minimum_observed_days,
            minimum_baseline_hours=minimum_baseline_hours, peak_ratio=peak_ratio,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "store_id": store_id, "source": source, "period_days": days,
        "period_start": start_date, "period_end": date.today(), **result,
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


@app.get("/api/v1/warehouse/pallet-rotation/portfolio-from-history", tags=["warehouse"])
def get_pallet_rotation_portfolio_from_history(
    store_id: int,
    current_hour: int,
    backroom_capacity_available: bool = False,
    days: int = 28,
    duration_hours: int = 1,
    source: SalesSource = "POS",
    minimum_observed_days: int = 7,
    conventional_minutes: float = 24,
    swap_minutes: float = 4,
    transport_minutes: float = 3,
    rebuild_minutes: float = 5,
    limit: int = 100,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Build a read-only SKU-specific pallet portfolio from recorded hourly history."""
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if isinstance(current_hour, bool) or not isinstance(current_hour, int) or not 0 <= current_hour <= 23:
        raise HTTPException(status_code=422, detail="current_hour must be an integer between 0 and 23")
    if isinstance(days, bool) or not isinstance(days, int) or not 7 <= days <= 90:
        raise HTTPException(status_code=422, detail="days must be an integer between 7 and 90")
    if isinstance(duration_hours, bool) or not isinstance(duration_hours, int) or not 1 <= duration_hours <= 4:
        raise HTTPException(status_code=422, detail="duration_hours must be an integer between 1 and 4")
    if (isinstance(minimum_observed_days, bool) or not isinstance(minimum_observed_days, int)
            or not 1 <= minimum_observed_days <= 90):
        raise HTTPException(status_code=422, detail="minimum_observed_days must be an integer between 1 and 90")
    numeric_inputs = {
        "conventional_minutes": conventional_minutes,
        "swap_minutes": swap_minutes,
        "transport_minutes": transport_minutes,
        "rebuild_minutes": rebuild_minutes,
    }
    for field, value in numeric_inputs.items():
        if isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"{field} must be numeric, not boolean")
        try:
            valid_number = math.isfinite(value) and value >= 0
        except (TypeError, ValueError, OverflowError):
            valid_number = False
        if not valid_number:
            raise HTTPException(status_code=422, detail=f"{field} must be finite and non-negative")

    try:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise PalletPortfolioInputError("limit must be an integer between 1 and 500")
        policies = db.query(models.PalletRotationPolicy).filter_by(
            store_id=store_id, is_enabled=True
        ).all()
        policy_by_product = {item.product_id: item for item in policies}
        if not policy_by_product:
            return {
                "store_id": store_id, "recommendations": [], "candidate_evidence": [],
                "considered": 0, "excluded": 0, "candidate_pallets": 0,
                "input_provenance": "HISTORICAL_HOURLY_SALES_AND_STORE_TRAFFIC",
                "simulation_only": True, "automatic_stock_movement_allowed": False,
            }

        pallets = db.query(models.StorePallet).filter(
            models.StorePallet.store_id == store_id,
            models.StorePallet.product_id.in_(list(policy_by_product)),
            models.StorePallet.status.in_(["ON_DISPLAY", "PARTIAL"]),
            models.StorePallet.location_type == "SALES_FLOOR",
        ).order_by(models.StorePallet.id).limit(5000).all()
        active_levels = {
            item.id: item
            for item in db.query(models.ProductPackagingLevel).filter(
                models.ProductPackagingLevel.id.in_([p.packaging_level_id for p in pallets] or [-1]),
                models.ProductPackagingLevel.is_active.is_(True),
                models.ProductPackagingLevel.package_type == "PALLET",
            ).all()
        }
        product_ids = {p.product_id for p in pallets}
        ready_pallets = db.query(models.StorePallet).filter(
            models.StorePallet.store_id == store_id,
            models.StorePallet.product_id.in_(list(product_ids) or [-1]),
            models.StorePallet.status == "READY",
            models.StorePallet.location_type.in_(["WAREHOUSE", "PREPARATION"]),
            or_(models.StorePallet.expiry_date.is_(None), models.StorePallet.expiry_date >= date.today()),
        ).all()
        ready_keys = [
            (p.product_id, p.packaging_level_id)
            for p in ready_pallets
            if p.packaging_level_id in active_levels
            and float(p.base_quantity) == float(active_levels[p.packaging_level_id].base_units_per_package)
        ]
        candidate_pallets = [
            p for p in pallets
            if p.packaging_level_id in active_levels and p.product_id in policy_by_product
        ]
        replacement_flags = allocate_ready_replacements(
            [(p.product_id, p.packaging_level_id) for p in candidate_pallets],
            ready_keys,
        )

        # Aggregate historical rows for all SKUs in a small fixed number of queries.
        history_start = date.today() - timedelta(days=days - 1)
        sales_daily = db.query(
            models.HourlySalesRecord.product_id.label("product_id"),
            models.HourlySalesRecord.business_date.label("business_date"),
            models.HourlySalesRecord.hour_of_day.label("hour"),
            func.sum(models.HourlySalesRecord.quantity).label("quantity"),
        ).filter(
            models.HourlySalesRecord.store_id == store_id,
            models.HourlySalesRecord.product_id.in_(list(product_ids) or [-1]),
            models.HourlySalesRecord.business_date >= history_start,
            models.HourlySalesRecord.business_date <= date.today(),
            models.HourlySalesRecord.source == source,
        ).group_by(
            models.HourlySalesRecord.product_id,
            models.HourlySalesRecord.business_date,
            models.HourlySalesRecord.hour_of_day,
        ).subquery()
        sales_rows = db.query(
            sales_daily.c.product_id,
            sales_daily.c.hour,
            func.avg(sales_daily.c.quantity).label("average_quantity"),
            func.count(sales_daily.c.business_date).label("observed_days"),
        ).group_by(sales_daily.c.product_id, sales_daily.c.hour).all()

        traffic_daily = db.query(
            models.HourlyStoreTrafficRecord.business_date.label("business_date"),
            models.HourlyStoreTrafficRecord.hour_of_day.label("hour"),
            func.sum(models.HourlyStoreTrafficRecord.customer_count).label("customers"),
        ).filter(
            models.HourlyStoreTrafficRecord.store_id == store_id,
            models.HourlyStoreTrafficRecord.business_date >= history_start,
            models.HourlyStoreTrafficRecord.business_date <= date.today(),
            models.HourlyStoreTrafficRecord.source == source,
        ).group_by(
            models.HourlyStoreTrafficRecord.business_date,
            models.HourlyStoreTrafficRecord.hour_of_day,
        ).subquery()
        traffic_rows = db.query(
            traffic_daily.c.hour,
            func.avg(traffic_daily.c.customers).label("average_customers"),
            func.count(traffic_daily.c.business_date).label("observed_days"),
        ).group_by(traffic_daily.c.hour).all()

        sales_by_product_hour = {
            (int(row.product_id), int(row.hour)): row for row in sales_rows
        }
        traffic_by_hour = {int(row.hour): row for row in traffic_rows}
        product_profiles = {
            product_id: [{
                "hour_of_day": hour,
                "average_daily_units": (
                    float(sales_by_product_hour[(product_id, hour)].average_quantity)
                    if (product_id, hour) in sales_by_product_hour else None
                ),
                "sales_observed_days": (
                    int(sales_by_product_hour[(product_id, hour)].observed_days)
                    if (product_id, hour) in sales_by_product_hour else 0
                ),
                "average_customers": (
                    float(traffic_by_hour[hour].average_customers)
                    if hour in traffic_by_hour else None
                ),
                "traffic_observed_days": (
                    int(traffic_by_hour[hour].observed_days)
                    if hour in traffic_by_hour else 0
                ),
            } for hour in range(24)]
            for product_id in product_ids
        }
        candidates = []
        for pallet, replacement_available in zip(candidate_pallets, replacement_flags):
            level = active_levels[pallet.packaging_level_id]
            policy = policy_by_product[pallet.product_id]
            candidates.append({
                "store_id": store_id,
                "product_id": pallet.product_id,
                "pallet_id": pallet.id,
                "residual_base_units": float(pallet.base_quantity),
                "pallet_capacity_base_units": float(level.base_units_per_package),
                "threshold_ratio": float(policy.threshold_ratio),
                "replacement_pallet_available": replacement_available,
                "backroom_capacity_available": backroom_capacity_available,
                "conventional_minutes": conventional_minutes,
                "swap_minutes": swap_minutes,
                "transport_minutes": transport_minutes,
                "rebuild_minutes": rebuild_minutes,
            })

        enriched = enrich_pallet_candidates_with_hourly_profiles(
            candidates, product_profiles, current_hour=current_hour,
            duration_hours=duration_hours,
            minimum_observed_days=minimum_observed_days,
        )
        planned_candidates = [
            row for row in enriched["candidates"]
            if row.get("forecast_consumption_until_low_traffic") is not None
            and row.get("traffic_level") in {"HIGH", "LOW"}
        ]
        interim_replenishment = [
            row for row in enriched["candidates"]
            if row.get("planning_recommendation") == "REPLENISH_CURRENT"
        ]
        insufficient_evidence = [
            row for row in enriched["candidates"]
            if row.get("traffic_level") == "UNKNOWN"
        ]
        plan = build_pallet_portfolio_plan(planned_candidates, limit=limit)
    except (PalletPortfolioInputError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "store_id": store_id,
        "current_hour": current_hour,
        "period_days": days,
        "source": source,
        "minimum_observed_days": minimum_observed_days,
        "recommendations": list(plan.recommendations),
        "interim_replenishment_required": interim_replenishment,
        "candidate_evidence": enriched["candidates"],
        "considered": plan.considered,
        "excluded": len(insufficient_evidence) + plan.excluded,
        "candidate_pallets": len(pallets),
        "insufficient_evidence_count": len(insufficient_evidence),
        "input_provenance": "HISTORICAL_HOURLY_SALES_AND_STORE_TRAFFIC",
        "simulation_only": True,
        "automatic_stock_movement_allowed": False,
    }


@app.get("/api/v1/warehouse/pallet-rotation/portfolio", tags=["warehouse"])
def get_pallet_rotation_portfolio(
    store_id: int,
    traffic_level: str,
    forecast_consumption_until_low_traffic: float,
    backroom_capacity_available: bool = False,
    conventional_minutes: float = 24,
    swap_minutes: float = 4,
    transport_minutes: float = 3,
    rebuild_minutes: float = 5,
    limit: int = 100,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Build a read-only, store-scoped portfolio from registered pallets and policies.

    Traffic, demand horizon and backroom capacity are explicit operator inputs;
    this endpoint does not present them as live sensor or forecast integrations.
    """
    actor = _request_user(db, request)
    _enforce_store_scope(actor, store_id)
    if db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")
    if traffic_level not in {"HIGH", "LOW", "UNKNOWN"}:
        raise HTTPException(status_code=422, detail="traffic_level must be HIGH, LOW or UNKNOWN")
    numeric_inputs = {
        "forecast_consumption_until_low_traffic": forecast_consumption_until_low_traffic,
        "conventional_minutes": conventional_minutes,
        "swap_minutes": swap_minutes,
        "transport_minutes": transport_minutes,
        "rebuild_minutes": rebuild_minutes,
    }
    for field, value in numeric_inputs.items():
        if isinstance(value, bool):
            raise HTTPException(status_code=422, detail=f"{field} must be numeric, not boolean")
        try:
            valid_number = math.isfinite(value) and value >= 0
        except (TypeError, ValueError, OverflowError):
            valid_number = False
        if not valid_number:
            raise HTTPException(status_code=422, detail=f"{field} must be finite and non-negative")
    try:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise PalletPortfolioInputError("limit must be an integer between 1 and 500")
        plan_limit = limit
        candidates_limit = max(1, min(plan_limit, 500))
        if plan_limit != candidates_limit:
            raise PalletPortfolioInputError("limit must be between 1 and 500")
        # The pure planner performs finite/non-negative validation for all numeric inputs.
        policies = db.query(models.PalletRotationPolicy).filter_by(
            store_id=store_id, is_enabled=True
        ).all()
        policy_by_product = {item.product_id: item for item in policies}
        if not policy_by_product:
            return {
                "store_id": store_id, "recommendations": [], "considered": 0,
                "excluded": 0, "candidate_pallets": 0,
                "input_provenance": "OPERATOR_SUPPLIED_TRAFFIC_DEMAND_AND_BACKROOM_CONFIRMATION",
                "simulation_only": True, "automatic_stock_movement_allowed": False,
            }

        pallets = db.query(models.StorePallet).filter(
            models.StorePallet.store_id == store_id,
            models.StorePallet.product_id.in_(list(policy_by_product)),
            models.StorePallet.status.in_(["ON_DISPLAY", "PARTIAL"]),
            models.StorePallet.location_type == "SALES_FLOOR",
        ).order_by(models.StorePallet.id).limit(5000).all()
        active_levels = {
            item.id: item
            for item in db.query(models.ProductPackagingLevel).filter(
                models.ProductPackagingLevel.id.in_([p.packaging_level_id for p in pallets] or [-1]),
                models.ProductPackagingLevel.is_active.is_(True),
                models.ProductPackagingLevel.package_type == "PALLET",
            ).all()
        }
        product_ids = {p.product_id for p in pallets}
        ready_pallets = db.query(models.StorePallet).filter(
            models.StorePallet.store_id == store_id,
            models.StorePallet.product_id.in_(list(product_ids) or [-1]),
            models.StorePallet.status == "READY",
            models.StorePallet.location_type.in_(["WAREHOUSE", "PREPARATION"]),
            or_(models.StorePallet.expiry_date.is_(None), models.StorePallet.expiry_date >= date.today()),
        ).all()
        ready_keys = [
            (p.product_id, p.packaging_level_id)
            for p in ready_pallets
            if p.packaging_level_id in active_levels
            and float(p.base_quantity) == float(active_levels[p.packaging_level_id].base_units_per_package)
        ]
        candidate_pallets = [
            p for p in pallets
            if p.packaging_level_id in active_levels and p.product_id in policy_by_product
        ]
        replacement_flags = allocate_ready_replacements(
            [(p.product_id, p.packaging_level_id) for p in candidate_pallets],
            ready_keys,
        )

        candidate_rows = []
        for pallet, replacement_available in zip(candidate_pallets, replacement_flags):
            level = active_levels[pallet.packaging_level_id]
            policy = policy_by_product[pallet.product_id]
            candidate_rows.append({
                "store_id": store_id,
                "product_id": pallet.product_id,
                "pallet_id": pallet.id,
                "residual_base_units": float(pallet.base_quantity),
                "pallet_capacity_base_units": float(level.base_units_per_package),
                "threshold_ratio": float(policy.threshold_ratio),
                "traffic_level": traffic_level,
                "replacement_pallet_available": replacement_available,
                "backroom_capacity_available": backroom_capacity_available,
                "forecast_consumption_until_low_traffic": forecast_consumption_until_low_traffic,
                "conventional_minutes": conventional_minutes,
                "swap_minutes": swap_minutes,
                "transport_minutes": transport_minutes,
                "rebuild_minutes": rebuild_minutes,
            })
        result = build_pallet_portfolio_plan(candidate_rows, limit=candidates_limit)
    except (PalletPortfolioInputError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return {
        "store_id": store_id,
        "recommendations": list(result.recommendations),
        "considered": result.considered,
        "excluded": result.excluded,
        "candidate_pallets": len(pallets),
        "input_provenance": "OPERATOR_SUPPLIED_TRAFFIC_DEMAND_AND_BACKROOM_CONFIRMATION",
        "simulation_only": True,
        "automatic_stock_movement_allowed": False,
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
    product = db.query(models.Product).filter(models.Product.id == payload.product_id).with_for_update().first()
    if product is None:
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


@app.get("/api/v1/inventory/freshness-policies", response_model=list[InventoryFreshnessPolicyRead], tags=["inventory"])
def list_inventory_freshness_policies(
    store_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication is required")
    if actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="Supervisor approval is required")
    _enforce_store_scope(actor, store_id)
    return (
        db.query(models.InventoryFreshnessPolicy)
        .filter(models.InventoryFreshnessPolicy.store_id == store_id)
        .order_by(models.InventoryFreshnessPolicy.source.asc())
        .all()
    )


@app.post("/api/v1/inventory/freshness-policies", response_model=InventoryFreshnessPolicyRead, tags=["inventory"])
def upsert_inventory_freshness_policy(
    payload: InventoryFreshnessPolicyUpsert,
    request: Request,
    db: Session = Depends(get_db),
):
    actor = _request_user(db, request)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication is required")
    if actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="Supervisor approval is required")
    _enforce_store_scope(actor, payload.store_id)
    if db.get(models.Store, payload.store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")

    policy = (
        db.query(models.InventoryFreshnessPolicy)
        .filter_by(store_id=payload.store_id, source=payload.source)
        .with_for_update()
        .first()
    )
    if policy is None:
        policy = models.InventoryFreshnessPolicy(
            store_id=payload.store_id,
            source=payload.source,
            max_age_minutes=payload.max_age_minutes,
        )
        db.add(policy)
    else:
        policy.max_age_minutes = payload.max_age_minutes

    try:
        db.commit()
    except IntegrityError as exc:
        # Two first-time writers can both observe no row; recover the unique-key race.
        db.rollback()
        policy = (
            db.query(models.InventoryFreshnessPolicy)
            .filter_by(store_id=payload.store_id, source=payload.source)
            .with_for_update()
            .first()
        )
        if policy is None:
            raise HTTPException(
                status_code=409,
                detail="Inventory freshness policy changed concurrently; retry the request",
            ) from exc
        policy.max_age_minutes = payload.max_age_minutes
        try:
            db.commit()
        except IntegrityError as retry_exc:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="Inventory freshness policy changed concurrently; retry the request",
            ) from retry_exc

    db.refresh(policy)
    return policy


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


@app.post(
    "/api/v1/tasks/{task_id}/reconcile-inventory",
    response_model=InventoryMovementRead,
    status_code=201,
    tags=["inventory"],
)
def reconcile_completed_replenishment(
    task_id: int,
    payload: InventoryReconciliationCreate,
    request: Request,
    db: Session = Depends(get_db),
):
    """Approve and record an immutable backroom-to-shelf stock movement."""
    actor = _request_user(db, request)
    if actor is None:
        raise HTTPException(status_code=401, detail="Authentication is required")
    if len(payload.reason.strip()) < 3:
        raise HTTPException(status_code=422, detail="A reconciliation reason with at least 3 non-space characters is required")
    if actor.role not in {"ADMIN", "SUPERVISOR"}:
        raise HTTPException(status_code=403, detail="Supervisor approval is required")

    task = (
        db.query(models.ReplenishmentTask)
        .filter(models.ReplenishmentTask.id == task_id)
        .with_for_update()
        .first()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    _enforce_store_scope(actor, task.store_id)
    product = db.query(models.Product).filter(models.Product.id == task.product_id).with_for_update().first()
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")

    existing = db.query(models.InventoryMovement).filter_by(task_id=task.id).first()
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={"code": "INVENTORY_ALREADY_RECONCILED", "movement_id": existing.id},
        )
    if task.status != "COMPLETED" or task.actual_quantity is None or float(task.actual_quantity) <= 0:
        raise HTTPException(
            status_code=409,
            detail={"code": "TASK_NOT_RECONCILABLE", "message": "A tarefa tem de estar concluída e ter quantidade efetivamente reposta positiva."},
        )
    if task.completed_at is None:
        raise HTTPException(status_code=409, detail={"code": "TASK_COMPLETION_TIME_MISSING"})

    completed_at = task.completed_at
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    else:
        completed_at = completed_at.astimezone(timezone.utc)
    now = models.utc_now()

    later_snapshot = (
        db.query(models.InventorySnapshot)
        .filter(
            models.InventorySnapshot.store_id == task.store_id,
            models.InventorySnapshot.product_id == task.product_id,
            models.InventorySnapshot.captured_at > completed_at,
        )
        .order_by(models.InventorySnapshot.captured_at.desc(), models.InventorySnapshot.id.desc())
        .first()
    )
    if later_snapshot is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVENTORY_EVIDENCE_AFTER_TASK",
                "snapshot_id": later_snapshot.id,
                "message": "Existe um snapshot posterior à conclusão da tarefa. Confirme a origem externa antes de reconciliar.",
            },
        )

    source_snapshot = (
        db.query(models.InventorySnapshot)
        .filter(
            models.InventorySnapshot.store_id == task.store_id,
            models.InventorySnapshot.product_id == task.product_id,
            models.InventorySnapshot.captured_at <= completed_at,
        )
        .order_by(models.InventorySnapshot.captured_at.desc(), models.InventorySnapshot.id.desc())
        .with_for_update()
        .first()
    )
    if source_snapshot is None:
        raise HTTPException(status_code=409, detail={"code": "INVENTORY_SNAPSHOT_MISSING"})
    captured_at = source_snapshot.captured_at
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=timezone.utc)
    else:
        captured_at = captured_at.astimezone(timezone.utc)
    age_minutes = (now - captured_at).total_seconds() / 60
    freshness_policy = (
        db.query(models.InventoryFreshnessPolicy)
        .filter_by(store_id=task.store_id, source=source_snapshot.source)
        .first()
    )
    max_age_minutes = freshness_policy.max_age_minutes if freshness_policy else 240
    if age_minutes < 0 or age_minutes > max_age_minutes:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INVENTORY_SNAPSHOT_STALE",
                "snapshot_id": source_snapshot.id,
                "source": source_snapshot.source,
                "age_minutes": round(age_minutes, 2),
                "max_age_minutes": max_age_minutes,
            },
        )

    prior_movements = (
        db.query(models.InventoryMovement)
        .filter(models.InventoryMovement.source_snapshot_id == source_snapshot.id)
        .with_for_update()
        .all()
    )
    already_moved = sum((Decimal(str(item.quantity)) for item in prior_movements), Decimal("0"))
    available = (
        Decimal(str(source_snapshot.on_hand_quantity))
        - Decimal(str(source_snapshot.reserved_quantity))
        - already_moved
    )
    quantity = Decimal(str(task.actual_quantity))
    if available < quantity:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "INSUFFICIENT_BACKROOM_STOCK",
                "available_quantity": float(max(available, Decimal("0"))),
                "requested_quantity": float(quantity),
            },
        )

    resulting_on_hand = Decimal(str(source_snapshot.on_hand_quantity)) - already_moved - quantity
    result_snapshot = models.InventorySnapshot(
        store_id=task.store_id,
        product_id=task.product_id,
        on_hand_quantity=resulting_on_hand,
        reserved_quantity=source_snapshot.reserved_quantity,
        source="MANUAL",
        external_reference=f"TASK-RECONCILIATION-{task.id}",
        captured_at=now,
        created_at=now,
    )
    movement = models.InventoryMovement(
        task_id=task.id,
        store_id=task.store_id,
        product_id=task.product_id,
        movement_type="BACKROOM_TO_SHELF",
        quantity=quantity,
        source_snapshot_id=source_snapshot.id,
        actor_user_id=actor.id,
        reason=payload.reason.strip(),
        created_at=now,
    )
    try:
        db.add(result_snapshot)
        db.flush()
        movement.result_snapshot_id = result_snapshot.id
        db.add(movement)
        db.flush()
        _record_task_event(
            db,
            task,
            "INVENTORY_RECONCILED",
            actor,
            from_status=task.status,
            to_status=task.status,
            actual_quantity=float(quantity),
            reason=(
                f"{payload.reason.strip()} | movimento={movement.id}; "
                f"snapshot_origem={source_snapshot.id}; snapshot_resultante={result_snapshot.id}"
            ),
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.query(models.InventoryMovement).filter_by(task_id=task.id).first()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={"code": "INVENTORY_ALREADY_RECONCILED", "movement_id": existing.id},
            ) from exc
        raise HTTPException(
            status_code=409,
            detail={"code": "INVENTORY_RECONCILIATION_CONFLICT", "message": "A reconciliação colidiu com outra alteração de inventário."},
        ) from exc
    db.refresh(movement)
    return movement



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
    include_stockout_risk: bool = False,
    risk_source: SalesSource = "POS",
    risk_days: int = 28,
    risk_lead_time_days: float = 3.0,
    risk_max_inventory_age_minutes: int = 240,
    include_effort_estimates: bool = False,
    effort_history_days: int = 90,
    effort_minimum_sample_size: int = 5,
    include_warehouse_pick_plan: bool = False,
    request: Request = None,
    db: Session = Depends(get_db),
):
    """Build a read-only, zone-grouped work queue with optional evidence-based stockout risk."""
    if stale_after_minutes < 1 or stale_after_minutes > 10080:
        raise HTTPException(status_code=422, detail="stale_after_minutes must be between 1 and 10080")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 500")
    if include_effort_estimates:
        if isinstance(effort_history_days, bool) or not isinstance(effort_history_days, int) or not 7 <= effort_history_days <= 730:
            raise HTTPException(status_code=422, detail="effort_history_days must be between 7 and 730")
        if isinstance(effort_minimum_sample_size, bool) or not isinstance(effort_minimum_sample_size, int) or not 2 <= effort_minimum_sample_size <= 100:
            raise HTTPException(status_code=422, detail="effort_minimum_sample_size must be between 2 and 100")
    if include_stockout_risk:
        if risk_days < 7 or risk_days > 365:
            raise HTTPException(status_code=422, detail="risk_days must be between 7 and 365")
        if risk_max_inventory_age_minutes < 1 or risk_max_inventory_age_minutes > 10080:
            raise HTTPException(status_code=422, detail="risk_max_inventory_age_minutes must be between 1 and 10080")
        if isinstance(risk_lead_time_days, bool) or not isinstance(risk_lead_time_days, (int, float)) or not 0 < risk_lead_time_days <= 365:
            raise HTTPException(status_code=422, detail="risk_lead_time_days must be greater than 0 and at most 365")
    _enforce_store_scope(_request_user(db, request), store_id)
    if not db.get(models.Store, store_id):
        raise HTTPException(status_code=404, detail="Store not found")

    recommendations = list_replenishment_recommendations(
        store_id=store_id, stale_after_minutes=stale_after_minutes, request=request, db=db,
    )
    risk_assessment = {
        "enabled": include_stockout_risk,
        "source": risk_source if include_stockout_risk else None,
        "history_days": risk_days if include_stockout_risk else None,
        "lead_time_days": risk_lead_time_days if include_stockout_risk else None,
        "basis": "COMPLETE_DAILY_SALES_AND_FRESH_INVENTORY" if include_stockout_risk else None,
        "unknown_risk_is_not_treated_as_low": True,
    }
    if include_stockout_risk and recommendations:
        product_ids = sorted({
            item["product_id"] for item in recommendations
            if isinstance(item.get("product_id"), int) and not isinstance(item.get("product_id"), bool)
        })
        through_date = date.today()
        history_start = through_date - timedelta(days=risk_days - 1)
        sales_records = db.query(models.DailySalesRecord).filter(
            models.DailySalesRecord.store_id == store_id,
            models.DailySalesRecord.product_id.in_(product_ids),
            models.DailySalesRecord.source == risk_source,
            models.DailySalesRecord.sales_date >= history_start,
            models.DailySalesRecord.sales_date <= through_date,
        ).all() if product_ids else []
        try:
            recommendations = enrich_replenishment_with_stockout_risk(
                recommendations,
                sales_records,
                through_date=through_date,
                now=models.utc_now(),
                days=risk_days,
                lead_time_days=float(risk_lead_time_days),
                max_inventory_age_minutes=risk_max_inventory_age_minutes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    effort_summary = {
        "enabled": include_effort_estimates,
        "history_days": effort_history_days if include_effort_estimates else None,
        "minimum_sample_size": effort_minimum_sample_size if include_effort_estimates else None,
        "metric": "ELAPSED_TIME_NOT_ACTIVE_LABOUR" if include_effort_estimates else None,
    }
    if include_effort_estimates and recommendations:
        effort_now = models.utc_now()
        effort_since = effort_now - timedelta(days=effort_history_days)
        history_rows = db.query(
            models.ReplenishmentTask, models.Zone.name,
        ).join(
            models.Shelf, models.ReplenishmentTask.shelf_id == models.Shelf.id,
        ).join(
            models.Zone, models.Shelf.zone_id == models.Zone.id,
        ).filter(
            models.ReplenishmentTask.store_id == store_id,
            models.ReplenishmentTask.status == "COMPLETED",
            models.ReplenishmentTask.started_at.isnot(None),
            models.ReplenishmentTask.completed_at.isnot(None),
            models.ReplenishmentTask.started_at >= effort_since,
            models.ReplenishmentTask.completed_at <= effort_now,
        ).all()
        effort_history = [
            {
                "zone_name": zone_name,
                "priority": task.priority,
                "started_at": task.started_at,
                "completed_at": task.completed_at,
            }
            for task, zone_name in history_rows
        ]
        effort_result = enrich_plan_with_effort_estimates(
            recommendations,
            effort_history,
            minimum_sample_size=effort_minimum_sample_size,
        )
        recommendations = effort_result["recommendations"]
        effort_summary.update(effort_result["summary"])

    active_tasks = db.query(models.ReplenishmentTask).filter(
        models.ReplenishmentTask.store_id == store_id,
        models.ReplenishmentTask.status.in_(("PENDING", "ASSIGNED", "IN_PROGRESS")),
    ).all()
    active_keys = {(task.shelf_id, task.product_id) for task in active_tasks}
    plan = build_replenishment_plan(recommendations, active_keys=active_keys, limit=limit)

    warehouse_pick_plan = {
        "enabled": include_warehouse_pick_plan,
        "status": "NOT_REQUESTED",
        "read_only": True,
        "stock_reserved": False,
        "stock_movement_allowed": False,
    }
    if include_warehouse_pick_plan:
        planned_items = [dict(item) for group in plan.groups for item in group.items]
        planned_product_ids = sorted({
            item["product_id"] for item in planned_items
            if isinstance(item.get("product_id"), int)
            and not isinstance(item.get("product_id"), bool)
        })
        profile_rows = db.query(
            models.WarehouseProductProfile.product_id,
            models.WarehouseProductProfile.temperature_requirement,
        ).filter(
            models.WarehouseProductProfile.product_id.in_(planned_product_ids)
        ).all() if planned_product_ids else []
        profile_by_product = {
            product_id: temperature for product_id, temperature in profile_rows
        }
        for item in planned_items:
            item["temperature_requirement"] = profile_by_product.get(item["product_id"])

        placement_rows = db.query(
            models.WarehouseProductPlacement,
            models.WarehouseLocation,
            models.WarehouseProductProfile.temperature_requirement,
        ).join(
            models.WarehouseLocation,
            models.WarehouseProductPlacement.location_id == models.WarehouseLocation.id,
        ).outerjoin(
            models.WarehouseProductProfile,
            models.WarehouseProductPlacement.product_id == models.WarehouseProductProfile.product_id,
        ).filter(
            models.WarehouseLocation.store_id == store_id,
            models.WarehouseLocation.is_active.is_(True),
            models.WarehouseProductPlacement.is_active.is_(True),
            models.WarehouseProductPlacement.product_id.in_(planned_product_ids),
        ).all() if planned_product_ids else []
        placements = [
            {
                "product_id": placement.product_id,
                "location_id": location.id,
                "location_code": location.code,
                "aisle": location.aisle,
                "rack": location.rack,
                "bin_code": location.bin_code,
                "distance_to_picking_m": location.distance_to_picking_m,
                "temperature_zone": location.temperature_zone,
                "quantity": placement.quantity,
                "is_active": placement.is_active,
            }
            for placement, location, _temperature in placement_rows
        ]
        warehouse_pick_plan = build_warehouse_pick_plan(planned_items, placements)
        warehouse_pick_plan["enabled"] = True

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
        "risk_assessment": risk_assessment,
        "effort_estimation": effort_summary,
        "warehouse_pick_plan": warehouse_pick_plan,
        "policy": "Proposta de organização; não cria nem atribui tarefas e não substitui validação humana.",
        "automatic_stock_movement_allowed": False,
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
    _lock_store_for_task_creation(db, payload.store_id)
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
    return _persist_new_task(
        db, item, actor,
        creation_reason="Tarefa criada através do fluxo operacional.",
    )



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

    _lock_store_for_task_creation(db, payload.store_id)
    active_task = db.query(models.ReplenishmentTask).filter(
        models.ReplenishmentTask.store_id == payload.store_id,
        models.ReplenishmentTask.shelf_id == payload.shelf_id,
        models.ReplenishmentTask.product_id == payload.product_id,
        models.ReplenishmentTask.status.in_(("PENDING", "ASSIGNED", "IN_PROGRESS")),
    ).first()
    if active_task is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ACTIVE_TASK_EXISTS",
                "task_id": active_task.id,
                "status": active_task.status,
                "message": "Já existe uma tarefa ativa para este produto nesta prateleira.",
            },
        )

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
    return _persist_new_task(
        db, item, actor,
        creation_reason="Tarefa criada através do fluxo de recomendação validada.",
    )



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


@app.get("/api/v1/operational-decisions", tags=["operations"])
def operational_decisions(
    request: Request,
    store_id: int | None = None,
    shelf_id: int | None = None,
    product_id: int | None = None,
    limit: int = 250,
    db: Session = Depends(get_db),
):
    """Evaluate product/shelf availability using recent recorded evidence.

    This endpoint is read-only: it does not create tasks or change inventory.
    """
    actor = _request_user(db, request)
    if actor is not None and actor.role == "EMPLOYEE":
        raise HTTPException(status_code=403, detail="Supervisor role required")
    if actor is not None and actor.role != "ADMIN":
        if actor.store_id is None:
            raise HTTPException(status_code=403, detail="User is not associated with a store")
        if store_id is not None and store_id != actor.store_id:
            raise HTTPException(status_code=403, detail="Access to this store is not allowed")
        store_id = actor.store_id
    if store_id is not None and db.get(models.Store, store_id) is None:
        raise HTTPException(status_code=404, detail="Store not found")

    limit = max(1, min(limit, 500))
    links_query = (
        db.query(models.ShelfProduct, models.Shelf, models.Zone, models.Product)
        .join(models.Shelf, models.ShelfProduct.shelf_id == models.Shelf.id)
        .join(models.Zone, models.Shelf.zone_id == models.Zone.id)
        .join(models.Product, models.ShelfProduct.product_id == models.Product.id)
        .filter(models.Product.is_active.is_(True))
    )
    if store_id is not None:
        links_query = links_query.filter(models.Zone.store_id == store_id)
    if shelf_id is not None:
        links_query = links_query.filter(models.Shelf.id == shelf_id)
    if product_id is not None:
        links_query = links_query.filter(models.Product.id == product_id)
    links = links_query.order_by(models.Zone.store_id, models.Shelf.id, models.Product.id).limit(limit).all()

    now = models.utc_now()
    today = now.date()
    sales_start = today - timedelta(days=6)
    decisions = []
    for link, shelf, zone, product in links:
        observation = (
            db.query(models.Observation)
            .filter(models.Observation.shelf_id == shelf.id)
            .order_by(models.Observation.observed_at.desc(), models.Observation.id.desc())
            .first()
        )
        snapshot = (
            db.query(models.InventorySnapshot)
            .filter(
                models.InventorySnapshot.store_id == zone.store_id,
                models.InventorySnapshot.product_id == product.id,
            )
            .order_by(models.InventorySnapshot.captured_at.desc(), models.InventorySnapshot.id.desc())
            .first()
        )
        sales_rows = (
            db.query(models.DailySalesRecord)
            .filter(
                models.DailySalesRecord.store_id == zone.store_id,
                models.DailySalesRecord.product_id == product.id,
                models.DailySalesRecord.sales_date >= sales_start,
                models.DailySalesRecord.sales_date <= today,
            )
            .all()
        )
        active_tasks = (
            db.query(models.ReplenishmentTask)
            .filter(
                models.ReplenishmentTask.store_id == zone.store_id,
                models.ReplenishmentTask.shelf_id == shelf.id,
                models.ReplenishmentTask.product_id == product.id,
                models.ReplenishmentTask.status.in_(("PENDING", "ASSIGNED", "IN_PROGRESS")),
            )
            .order_by(models.ReplenishmentTask.created_at.desc())
            .all()
        )

        def aware(value):
            if value is None:
                return None
            return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

        observation_input = None
        if observation is not None:
            observation_input = {
                "status": observation.status,
                "observed_at": aware(observation.observed_at),
                "confidence": observation.confidence,
                "source": observation.source,
            }
        # InventorySnapshot is explicitly a backroom-stock record. Keep it
        # separate from shelf quantity: using it as shelf inventory would
        # distort display coverage and replenishment quantities.
        backroom_inventory = None
        backroom_available_for_refill = None
        if snapshot is not None:
            snapshot_at = aware(snapshot.captured_at)
            snapshot_age_minutes = max(0.0, (aware(now) - snapshot_at).total_seconds() / 60)
            snapshot_is_fresh = snapshot_at <= aware(now) and snapshot_age_minutes <= 240
            backroom_inventory = {
                "on_hand_quantity": float(snapshot.on_hand_quantity),
                "reserved_quantity": float(snapshot.reserved_quantity),
                "available_quantity": float(snapshot.available_quantity),
                "source": snapshot.source,
                "captured_at": snapshot_at.isoformat(),
                "age_minutes": round(snapshot_age_minutes, 1),
                "is_fresh": snapshot_is_fresh,
            }
            if snapshot_is_fresh:
                backroom_available_for_refill = float(snapshot.available_quantity)

        # A quantity suggestion requires a measured shelf count, a fresh and
        # sufficiently confident visual observation, and fresh backroom stock.
        # Status-only detections never become invented unit counts.
        replenishment_assessment = None
        if observation is not None and observation.status in ("LOW_STOCK", "EMPTY"):
            observation_at = aware(observation.observed_at)
            observation_age_minutes = max(0.0, (aware(now) - observation_at).total_seconds() / 60)
            if observation_at > aware(now):
                replenishment_assessment = {
                    "status": "FUTURE_OBSERVATION",
                    "suggested_quantity": None,
                    "shelf_gap_quantity": None,
                    "remaining_gap_quantity": None,
                    "requires_human_review": True,
                    "explanation": "A observação tem uma data futura e não pode suportar uma proposta de reposição.",
                }
            elif observation.observed_quantity is not None:
                try:
                    refill = suggest_shelf_refill(ShelfRefillInput(
                        shelf_quantity=float(observation.observed_quantity),
                        target_quantity=float(link.target_quantity),
                        min_display_quantity=float(link.min_display_quantity),
                        backroom_available_quantity=backroom_available_for_refill,
                        observation_confidence=observation.confidence,
                        observation_age_minutes=observation_age_minutes,
                        max_observation_age_minutes=120,
                    ))
                    replenishment_assessment = {
                        "status": refill.status,
                        "suggested_quantity": refill.suggested_quantity,
                        "shelf_gap_quantity": refill.shelf_gap_quantity,
                        "remaining_gap_quantity": refill.remaining_gap_quantity,
                        "requires_human_review": refill.requires_human_review,
                        "explanation": refill.explanation,
                        "observation_age_minutes": round(observation_age_minutes, 1),
                        "inventory_freshness_required": True,
                    }
                except ValueError as exc:
                    replenishment_assessment = {
                        "status": "INVALID_EVIDENCE",
                        "suggested_quantity": None,
                        "shelf_gap_quantity": None,
                        "remaining_gap_quantity": None,
                        "requires_human_review": True,
                        "explanation": "Os dados de reposição não passaram a validação.",
                        "warnings": [str(exc)],
                    }
            else:
                replenishment_assessment = {
                    "status": "QUANTITY_NOT_MEASURED",
                    "suggested_quantity": None,
                    "shelf_gap_quantity": None,
                    "remaining_gap_quantity": None,
                    "requires_human_review": True,
                    "explanation": "Existe uma deteção visual, mas não uma contagem física validada da quantidade na prateleira.",
                }
        inventory_input = None
        forecast_input = None
        if sales_rows:
            total_sold = sum(float(row.quantity) for row in sales_rows)
            recorded_sales_days = len({row.sales_date for row in sales_rows})
            forecast_input = {
                "predicted_units": total_sold / recorded_sales_days,
                "horizon_hours": 24,
                "generated_at": aware(now),
                "method": "RECORDED_DAY_DAILY_AVERAGE",
                "source_records": len(sales_rows),
                "observed_sales_days": recorded_sales_days,
                "sales_window_start": sales_start.isoformat(),
                "sales_window_end": today.isoformat(),
            }
        try:
            result = evaluate_shelf_decision(
                now=aware(now),
                observation=observation_input,
                inventory=inventory_input,
                demand_forecast=forecast_input,
                active_tasks=[{"id": task.id, "status": task.status} for task in active_tasks],
            )
        except ValueError as exc:
            result = {
                "status": "INSUFFICIENT_EVIDENCE",
                "priority": "NONE",
                "reason": "A evidência registada não passou a validação do motor de decisão.",
                "suggested_replenishment_quantity": None,
                "automatic_stock_movement_allowed": False,
                "requires_human_approval": False,
                "evidence": [],
                "warnings": [str(exc)],
                "evaluated_at": aware(now).isoformat(),
            }
        if backroom_inventory is not None:
            result["warnings"] = list(dict.fromkeys([
                *result.get("warnings", []),
                "O stock apresentado separadamente corresponde à retaguarda; não foi usado como quantidade na prateleira nem para calcular cobertura de exposição.",
            ]))
        decisions.append({
            "backroom_inventory": backroom_inventory,
            "replenishment_assessment": replenishment_assessment,
            "store_id": zone.store_id,
            "zone_name": zone.name,
            "shelf_id": shelf.id,
            "shelf_code": shelf.code,
            "product_id": product.id,
            "product_sku": product.sku,
            "product_name": product.name,
            "decision": result,
        })

    status_order = {
        "ACTION_RECOMMENDED": 0,
        "ALREADY_IN_PROGRESS": 1,
        "INSUFFICIENT_EVIDENCE": 2,
        "MONITOR": 3,
    }
    priority_order = {"HIGH": 0, "NORMAL": 1, "NONE": 2}
    decisions.sort(key=lambda item: (
        status_order.get(item["decision"].get("status"), 4),
        priority_order.get(item["decision"].get("priority"), 3),
        item["decision"].get("inventory_coverage_hours")
            if item["decision"].get("inventory_coverage_hours") is not None else float("inf"),
        item["shelf_id"],
        item["product_id"],
    ))

    counts = {}
    priority_counts = {}
    zone_rollups = {}
    for item in decisions:
        decision = item["decision"]
        key = decision["status"]
        counts[key] = counts.get(key, 0) + 1
        priority = decision.get("priority", "NONE")
        priority_counts[priority] = priority_counts.get(priority, 0) + 1
        zone_key = (item["store_id"], item["zone_name"])
        rollup = zone_rollups.setdefault(zone_key, {
            "store_id": item["store_id"], "zone_name": item["zone_name"],
            "items_evaluated": 0, "action_recommended": 0,
            "high_priority": 0, "already_in_progress": 0,
            "insufficient_evidence": 0, "monitor": 0,
            "lowest_coverage_hours": None, "urgent_items": [],
        })
        rollup["items_evaluated"] += 1
        if key == "ACTION_RECOMMENDED":
            rollup["action_recommended"] += 1
            if priority == "HIGH":
                rollup["high_priority"] += 1
            coverage = decision.get("inventory_coverage_hours")
            if coverage is not None and (
                rollup["lowest_coverage_hours"] is None
                or coverage < rollup["lowest_coverage_hours"]
            ):
                rollup["lowest_coverage_hours"] = coverage
            rollup["urgent_items"].append({
                "product_id": item["product_id"],
                "product_name": item["product_name"],
                "product_sku": item["product_sku"],
                "shelf_id": item["shelf_id"],
                "shelf_code": item["shelf_code"],
                "priority": priority,
                "reason": decision.get("reason"),
                "inventory_coverage_hours": coverage,
            })
        elif key == "ALREADY_IN_PROGRESS":
            rollup["already_in_progress"] += 1
        elif key == "INSUFFICIENT_EVIDENCE":
            rollup["insufficient_evidence"] += 1
        else:
            rollup["monitor"] += 1

    zone_summaries = []
    for rollup in zone_rollups.values():
        rollup["urgent_items"].sort(key=lambda row: (
            0 if row["priority"] == "HIGH" else 1,
            row["inventory_coverage_hours"] if row["inventory_coverage_hours"] is not None else float("inf"),
            row["shelf_id"], row["product_id"],
        ))
        rollup["urgent_items"] = rollup["urgent_items"][:3]
        zone_summaries.append(rollup)
    zone_summaries.sort(key=lambda row: (
        -row["high_priority"], -row["action_recommended"],
        row["lowest_coverage_hours"] if row["lowest_coverage_hours"] is not None else float("inf"),
        row["store_id"], row["zone_name"],
    ))
    return {
        "generated_at": aware(now).isoformat(),
        "store_id": store_id,
        "count": len(decisions),
        "status_counts": counts,
        "priority_counts": priority_counts,
        "zone_summaries": zone_summaries,
        "forecast_policy": "Média diária simples dos dias com vendas registadas na janela móvel de sete dias; não ajusta promoções, sazonalidade, tráfego ou dias sem registo.",
        "decisions": decisions,
        "side_effects": {"tasks_created": 0, "inventory_changed": False},
    }


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
    task = db.query(models.ReplenishmentTask).filter(models.ReplenishmentTask.id == task_id).with_for_update().first()
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
        raise HTTPException(status_code=409, detail=f"Transition from {task.status} to {payload.status} is not allowed")

    if payload.status == "COMPLETED":
        if payload.actual_quantity is None:
            raise HTTPException(status_code=422, detail={"code": "ACTUAL_QUANTITY_REQUIRED", "message": "Indique a quantidade efetivamente reposta."})
        if task.requested_quantity is not None and payload.actual_quantity > float(task.requested_quantity):
            raise HTTPException(status_code=409, detail={"code": "ACTUAL_QUANTITY_EXCEEDS_REQUESTED", "requested_quantity": float(task.requested_quantity)})
        if task.requested_quantity is not None and payload.actual_quantity < float(task.requested_quantity) and not payload.exception_reason:
            raise HTTPException(status_code=422, detail={"code": "PARTIAL_COMPLETION_REASON_REQUIRED", "message": "Explique a diferença entre a quantidade pedida e a quantidade reposta."})
    elif payload.status == "CANCELLED":
        if not payload.exception_reason:
            raise HTTPException(status_code=422, detail={"code": "CANCELLATION_REASON_REQUIRED", "message": "Indique o motivo do cancelamento."})
        if payload.actual_quantity is not None:
            raise HTTPException(status_code=422, detail="Actual quantity is only valid when completing a task")
    elif payload.actual_quantity is not None or payload.exception_reason is not None:
        raise HTTPException(status_code=422, detail="Quantity and exception reason are only valid for completion or cancellation")

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

    previous_status = task.status
    now = models.utc_now()
    task.status = payload.status
    task.updated_at = now
    if payload.status == "IN_PROGRESS":
        task.started_at = now
    elif payload.status == "COMPLETED":
        task.completed_at = now
        task.actual_quantity = payload.actual_quantity
        task.exception_reason = payload.exception_reason
    elif payload.status == "CANCELLED":
        task.exception_reason = payload.exception_reason

    _record_task_event(
        db, task, "STATUS_CHANGED", actor, from_status=previous_status,
        to_status=payload.status, actual_quantity=payload.actual_quantity,
        reason=payload.exception_reason,
    )
    db.commit()
    db.refresh(task)
    return task


@app.get("/api/v1/tasks/{task_id}/events", response_model=list[ReplenishmentTaskEventRead], tags=["tasks"])
def list_replenishment_task_events(task_id: int, request: Request, db: Session = Depends(get_db)):
    task = db.get(models.ReplenishmentTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    actor = _request_user(db, request)
    if actor is not None and actor.role != "ADMIN" and task.store_id != actor.store_id:
        raise HTTPException(status_code=403, detail="Access to this task is not allowed")
    return (
        db.query(models.ReplenishmentTaskEvent)
        .filter(models.ReplenishmentTaskEvent.task_id == task_id)
        .order_by(models.ReplenishmentTaskEvent.created_at.asc(), models.ReplenishmentTaskEvent.id.asc())
        .all()
    )


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

@app.post(
    "/api/v1/tasks/from-operational-decision",
    response_model=ReplenishmentTaskRead,
    status_code=201,
    tags=["tasks"],
)
def create_task_from_operational_decision(
    payload: ReplenishmentTaskCreate,
    request: Request,
    approved: bool = False,
    db: Session = Depends(get_db),
):
    """Create a replenishment task only after explicit approval and fresh re-evaluation."""
    actor = _request_user(db, request)
    if actor is not None and actor.role == "EMPLOYEE":
        raise HTTPException(status_code=403, detail="Supervisor role required")
    if actor is not None and actor.role != "ADMIN" and actor.store_id != payload.store_id:
        raise HTTPException(status_code=403, detail="Access to this store is not allowed")
    if not approved:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "HUMAN_APPROVAL_REQUIRED",
                "message": "Confirme explicitamente a aprovação antes de criar a tarefa.",
            },
        )

    evaluation = operational_decisions(
        request=request,
        store_id=payload.store_id,
        shelf_id=payload.shelf_id,
        product_id=payload.product_id,
        limit=500,
        db=db,
    )
    item = next(
        (
            row for row in evaluation["decisions"]
            if row["shelf_id"] == payload.shelf_id
            and row["product_id"] == payload.product_id
        ),
        None,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Produto não associado a esta prateleira nesta loja")
    assessment = item.get("replenishment_assessment") or {}
    if assessment.get("status") != "NEEDS_REPLENISHMENT":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REPLENISHMENT_NOT_APPROVED_BY_EVIDENCE",
                "assessment_status": assessment.get("status", "NOT_AVAILABLE"),
                "message": "A evidência atual não suporta uma tarefa quantitativa de reposição.",
            },
        )

    suggested = assessment.get("suggested_quantity")
    if suggested is None or suggested <= 0:
        raise HTTPException(status_code=409, detail="Não existe uma quantidade de reposição validada")
    requested = payload.requested_quantity if payload.requested_quantity is not None else suggested
    if requested <= 0 or requested > suggested:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "REQUEST_EXCEEDS_APPROVED_QUANTITY",
                "approved_quantity": suggested,
                "requested_quantity": requested,
                "message": "A quantidade da tarefa não pode exceder a proposta validada.",
            },
        )
    backroom = item.get("backroom_inventory") or {}
    available = backroom.get("available_quantity")
    if not backroom.get("is_fresh") or available is None or requested > available:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "BACKROOM_STOCK_NOT_VALID",
                "available_quantity": available,
                "message": "O stock de retaguarda deixou de ser válido ou suficiente.",
            },
        )

    _lock_store_for_task_creation(db, payload.store_id)
    active_task = db.query(models.ReplenishmentTask).filter(
        models.ReplenishmentTask.store_id == payload.store_id,
        models.ReplenishmentTask.shelf_id == payload.shelf_id,
        models.ReplenishmentTask.product_id == payload.product_id,
        models.ReplenishmentTask.status.in_(("PENDING", "ASSIGNED", "IN_PROGRESS")),
    ).first()
    if active_task is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "ACTIVE_TASK_EXISTS",
                "task_id": active_task.id,
                "status": active_task.status,
            },
        )

    assigned_user_id = payload.assigned_user_id
    assigned_to = payload.assigned_to
    if assigned_user_id is not None:
        assignee = db.get(models.User, assigned_user_id)
        if assignee is None or not assignee.is_active or assignee.store_id != payload.store_id:
            raise HTTPException(status_code=422, detail="Assigned user must be active and belong to this store")
        assigned_to = assignee.full_name

    approved_by = actor.full_name if actor is not None else "ambiente de teste sem identidade"
    approved_at = models.utc_now().isoformat()
    approval_note = (
        f"Aprovado manualmente por {approved_by} em {approved_at}, após reavaliação operacional. "
        f"Quantidade proposta: {suggested}; quantidade aprovada: {requested}."
    )
    notes = f"{payload.notes.strip()}\n{approval_note}" if payload.notes and payload.notes.strip() else approval_note
    task = models.ReplenishmentTask(
        store_id=payload.store_id,
        shelf_id=payload.shelf_id,
        product_id=payload.product_id,
        priority=payload.priority,
        status="ASSIGNED" if (assigned_to or assigned_user_id) else "PENDING",
        assigned_to=assigned_to,
        assigned_user_id=assigned_user_id,
        requested_quantity=requested,
        notes=notes,
    )
    return _persist_new_task(
        db, task, actor,
        creation_reason="Tarefa criada a partir de decisão operacional aprovada.",
        approval_quantity=requested,
        approval_reason=f"Proposta operacional aprovada; quantidade sugerida={suggested}.",
    )

