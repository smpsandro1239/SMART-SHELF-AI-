from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ObservationStatus = Literal["NORMAL", "LOW_STOCK", "EMPTY", "MISPLACED", "DAMAGED", "UNKNOWN", "OCCLUDED"]
ObservationSource = Literal["fixed_camera", "robot", "mobile", "simulation"]


class StoreCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)


class StoreRead(StoreCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ZoneCreate(BaseModel):
    store_id: int
    name: str = Field(min_length=1, max_length=120)


class ZoneRead(ZoneCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ShelfCreate(BaseModel):
    zone_id: int
    code: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=250)


class ShelfRead(ShelfCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ObservationCreate(BaseModel):
    shelf_id: int
    source: ObservationSource = "mobile"
    status: ObservationStatus = "UNKNOWN"
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = None
    observed_at: datetime | None = None
    model_version: str | None = Field(default=None, max_length=100)


class ObservationRead(BaseModel):
    id: int
    shelf_id: int
    source: str
    status: str
    confidence: float | None
    notes: str | None
    observed_at: datetime
    model_version: str | None
    model_config = ConfigDict(from_attributes=True)


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    brand: str | None = Field(default=None, max_length=120)
    unit: str = Field(default="un", min_length=1, max_length=30)
    is_active: bool = True


class ProductRead(ProductCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfProductCreate(BaseModel):
    shelf_id: int
    product_id: int
    target_quantity: int = Field(default=1, gt=0)
    min_display_quantity: int = Field(default=0, ge=0)
    position: str | None = Field(default=None, max_length=80)


class ShelfProductRead(ShelfProductCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)


InventorySource = Literal["ERP", "WMS", "POS", "MANUAL", "IMPORT"]


class InventorySnapshotCreate(BaseModel):
    store_id: int
    product_id: int
    on_hand_quantity: float = Field(ge=0)
    reserved_quantity: float = Field(default=0, ge=0)
    source: InventorySource
    external_reference: str | None = Field(default=None, max_length=120)
    captured_at: datetime | None = None

    @model_validator(mode="after")
    def reserved_must_not_exceed_on_hand(self):
        if self.reserved_quantity > self.on_hand_quantity:
            raise ValueError("reserved_quantity cannot exceed on_hand_quantity")
        return self


class InventorySnapshotRead(BaseModel):
    id: int
    store_id: int
    product_id: int
    on_hand_quantity: float
    reserved_quantity: float
    available_quantity: float
    source: str
    external_reference: str | None
    captured_at: datetime
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
