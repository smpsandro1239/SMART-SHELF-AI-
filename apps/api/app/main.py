from datetime import timedelta, timezone

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import func
from jwt import InvalidTokenError

from app.config import settings
from app.database import get_db, SessionLocal
from app import models
from app.security import hash_password, verify_password, create_access_token, decode_access_token
from app.schemas import (
    ObservationCreate, ObservationRead, ShelfCreate, ShelfRead,
    StoreCreate, StoreRead, ZoneCreate, ZoneRead,
    ProductCreate, ProductRead, ShelfProductCreate, ShelfProductRead,
    InventorySnapshotCreate, InventorySnapshotRead, ReplenishmentRecommendationRead,
    ReplenishmentTaskCreate, ReplenishmentTaskStatusUpdate, ReplenishmentTaskRead,
    BootstrapAdminCreate, LoginRequest, TokenRead, UserRead, UserCreate,
)

app = FastAPI(title=settings.app_name, version="0.2.0", description="Operational API for SMART SHELF AI.")




PUBLIC_API_PATHS = {"/api/v1/auth/bootstrap", "/api/v1/auth/login"}


@app.middleware("http")
async def require_api_authentication(request: Request, call_next):
    if settings.app_env == "test":
        return await call_next(request)
    if not request.url.path.startswith("/api/v1/") or request.url.path in PUBLIC_API_PATHS:
        return await call_next(request)
    role = request.headers.get("X-Role")  # ignored; role is always read from the database token subject
    del role
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
        if admin_only and user.role != "ADMIN":
            return JSONResponse(status_code=403, content={"detail": "Administrator role required"})
        if user.role == "EMPLOYEE" and not (
            method == "GET" and (path == "/api/v1/tasks" or path == "/api/v1/auth/me")
        ):
            return JSONResponse(status_code=403, content={"detail": "Employee role has read-only task access"})
        if user.role == "SUPERVISOR" and path.startswith("/api/v1/auth/users"):
            return JSONResponse(status_code=403, content={"detail": "Administrator role required"})
    finally:
        db.close()
    return await call_next(request)



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
def list_stores(db: Session = Depends(get_db)):
    return db.query(models.Store).order_by(models.Store.id).all()


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
def list_shelves(db: Session = Depends(get_db)):
    return db.query(models.Shelf).order_by(models.Shelf.id).all()


@app.post("/api/v1/observations", response_model=ObservationRead, status_code=201, tags=["observations"])
def create_observation(payload: ObservationCreate, db: Session = Depends(get_db)):
    if not db.get(models.Shelf, payload.shelf_id):
        raise HTTPException(status_code=404, detail="Shelf not found")
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
def list_observations(shelf_id: int | None = None, limit: int = 100, db: Session = Depends(get_db)):
    limit = max(1, min(limit, 500))
    query = db.query(models.Observation)
    if shelf_id is not None:
        query = query.filter(models.Observation.shelf_id == shelf_id)
    return query.order_by(models.Observation.observed_at.desc()).limit(limit).all()


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
def list_shelf_products(shelf_id: int | None = None, product_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(models.ShelfProduct)
    if shelf_id is not None:
        query = query.filter(models.ShelfProduct.shelf_id == shelf_id)
    if product_id is not None:
        query = query.filter(models.ShelfProduct.product_id == product_id)
    return query.order_by(models.ShelfProduct.shelf_id, models.ShelfProduct.position).all()



@app.post("/api/v1/inventory/snapshots", response_model=InventorySnapshotRead, status_code=201, tags=["inventory"])
def create_inventory_snapshot(payload: InventorySnapshotCreate, db: Session = Depends(get_db)):
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
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    query = db.query(models.InventorySnapshot)
    if store_id is not None:
        query = query.filter(models.InventorySnapshot.store_id == store_id)
    if product_id is not None:
        query = query.filter(models.InventorySnapshot.product_id == product_id)
    return query.order_by(models.InventorySnapshot.captured_at.desc(), models.InventorySnapshot.id.desc()).limit(limit).all()


@app.get("/api/v1/inventory/latest", response_model=InventorySnapshotRead, tags=["inventory"])
def get_latest_inventory_snapshot(
    store_id: int,
    product_id: int,
    db: Session = Depends(get_db),
):
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
    db: Session = Depends(get_db),
):
    """Combine shelf observations with the latest backroom inventory snapshot.

    A visual status is not a unit count, so this endpoint never invents an
    exact replenishment quantity.
    """
    if stale_after_minutes < 1 or stale_after_minutes > 10080:
        raise HTTPException(status_code=422, detail="stale_after_minutes must be between 1 and 10080")
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

        if observation is None:
            status = "STALE_OBSERVATION"
            explanation = "Ainda não existe observação registada para esta prateleira."
        else:
            observed_at = observation.observed_at
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            if now - observed_at > timedelta(minutes=stale_after_minutes):
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
                else:
                    status = "NEEDS_REPLENISHMENT"
                    explanation = "A prateleira apresenta baixa disponibilidade e existe stock na retaguarda."
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
            "observed_at": observation.observed_at if observation else None,
            "inventory_available_quantity": available,
            "inventory_captured_at": inventory.captured_at if inventory else None,
            "recommendation_status": status,
            "suggested_quantity": None,
            "explanation": explanation,
        })
    return recommendations



@app.post("/api/v1/tasks", response_model=ReplenishmentTaskRead, status_code=201, tags=["tasks"])
def create_replenishment_task(payload: ReplenishmentTaskCreate, db: Session = Depends(get_db)):
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
    stale_after_minutes: int = 120,
    db: Session = Depends(get_db),
):
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
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 500))
    query = db.query(models.ReplenishmentTask)
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
    db: Session = Depends(get_db),
):
    task = db.get(models.ReplenishmentTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

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
