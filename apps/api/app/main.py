from datetime import timedelta, timezone
from pathlib import Path
from uuid import uuid4
import hashlib

from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import func
from jwt import InvalidTokenError

from app.config import settings
from app.database import get_db, SessionLocal
from app import models
from app.security import hash_password, verify_password, create_access_token, decode_access_token
from app.product_text import normalize_product_text
from app.replenishment_policy import ShelfRefillInput, suggest_shelf_refill
from app.schemas import (
    ObservationCreate, ObservationRead, ShelfCreate, ShelfRead,
    StoreCreate, StoreRead, ZoneCreate, ZoneRead,
    ProductCreate, ProductRead, ShelfProductCreate, ShelfProductRead,
    InventorySnapshotCreate, InventorySnapshotRead, ReplenishmentRecommendationRead,
    ReplenishmentTaskCreate, ReplenishmentTaskStatusUpdate, ReplenishmentTaskRead,
    BootstrapAdminCreate, LoginRequest, TokenRead, UserRead, UserCreate, ShelfImageRead,
    ShelfImageDetectionRead, ProductEmbeddingExemplarCreate,
    ProductEmbeddingExemplarReview, ProductEmbeddingExemplarRead,
    DetectionSkuReviewCreate, DetectionSkuReviewRead,
    ShelfImageOCRRunCreate, ShelfImageOCRRunRead, ShelfImageOCREvidenceRead,
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
            })
        )
        supervisor_or_admin = (
            path == "/api/v1/product-embedding-exemplars"
            or path.startswith("/api/v1/product-embedding-exemplars/")
            or (method == "POST" and path.startswith("/api/v1/shelf-image-detections/"))
            or (method == "POST" and path.startswith("/api/v1/shelf-images/") and path.endswith("/ocr-runs"))
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
            allowed_employee_ocr_evidence = method == "GET" and path.startswith("/api/v1/shelf-images/") and path.endswith("/ocr-evidence")
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


@app.post("/api/v1/shelf-images", response_model=ShelfImageRead, status_code=201, tags=["computer-vision"])
async def upload_shelf_image(
    request: Request,
    shelf_id: int = Form(...),
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


@app.post(
    "/api/v1/shelf-image-detections/{detection_id}/reviews",
    response_model=DetectionSkuReviewRead,
    status_code=201,
    tags=["computer-vision"],
)

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
    if data["requested_quantity"] is None:
        data["requested_quantity"] = recommendation["suggested_quantity"]
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
