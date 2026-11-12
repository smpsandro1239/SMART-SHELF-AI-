from datetime import timezone

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app import models
from app.schemas import (
    ObservationCreate, ObservationRead, ShelfCreate, ShelfRead,
    StoreCreate, StoreRead, ZoneCreate, ZoneRead,
    ProductCreate, ProductRead, ShelfProductCreate, ShelfProductRead,
)

app = FastAPI(title=settings.app_name, version="0.2.0", description="Operational API for SMART SHELF AI.")


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
