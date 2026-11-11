from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
