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


ReplenishmentStatus = Literal[
    "NEEDS_REPLENISHMENT",
    "BACKROOM_OUT_OF_STOCK",
    "INVENTORY_UNKNOWN",
    "STALE_OBSERVATION",
    "LOW_CONFIDENCE",
    "NO_ACTION",
]


class ReplenishmentRecommendationRead(BaseModel):
    store_id: int
    shelf_id: int
    shelf_code: str
    product_id: int
    product_name: str
    sku: str
    observation_status: str | None
    observation_confidence: float | None
    observed_at: datetime | None
    inventory_available_quantity: float | None
    inventory_captured_at: datetime | None
    recommendation_status: ReplenishmentStatus
    suggested_quantity: float | None = None
    explanation: str


TaskPriority = Literal["LOW", "NORMAL", "HIGH", "URGENT"]
TaskStatus = Literal["PENDING", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "CANCELLED"]


class ReplenishmentTaskCreate(BaseModel):
    store_id: int
    shelf_id: int
    product_id: int
    priority: TaskPriority = "NORMAL"
    assigned_to: str | None = Field(default=None, min_length=1, max_length=120)
    assigned_user_id: int | None = None
    requested_quantity: float | None = Field(default=None, gt=0)
    notes: str | None = Field(default=None, max_length=2000)


class ReplenishmentTaskStatusUpdate(BaseModel):
    status: TaskStatus
    assigned_to: str | None = Field(default=None, min_length=1, max_length=120)
    assigned_user_id: int | None = None


class ReplenishmentTaskRead(BaseModel):
    id: int
    store_id: int
    shelf_id: int
    product_id: int
    priority: TaskPriority
    status: TaskStatus
    assigned_to: str | None
    assigned_user_id: int | None
    requested_quantity: float | None
    notes: str | None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    model_config = ConfigDict(from_attributes=True)


UserRole = Literal["ADMIN", "SUPERVISOR", "EMPLOYEE"]


class BootstrapAdminCreate(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class UserRead(BaseModel):
    id: int
    store_id: int | None
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class TokenRead(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserRead

class UserCreate(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=128)
    role: UserRole = "EMPLOYEE"
    store_id: int | None = None


class ShelfImageRead(BaseModel):
    id: int
    shelf_id: int
    original_filename: str
    mime_type: str
    file_size_bytes: int
    sha256: str
    analysis_status: Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]
    analysis_error: str | None
    analysis_started_at: datetime | None
    analysis_completed_at: datetime | None
    model_version: str | None
    captured_at: datetime
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfImageDetectionRead(BaseModel):
    id: int
    shelf_image_id: int
    product_id: int | None
    label: str
    confidence: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    model_version: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
