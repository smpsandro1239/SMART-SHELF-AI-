from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    product_id: int | None = None
    source: ObservationSource = "mobile"
    status: ObservationStatus = "UNKNOWN"
    confidence: float | None = Field(default=None, ge=0, le=1)
    observed_quantity: float | None = Field(default=None, ge=0)
    notes: str | None = None
    observed_at: datetime | None = None
    model_version: str | None = Field(default=None, max_length=100)


class DetectionObservationCreate(BaseModel):
    """Human-confirmed SKU and observation state for a demo detection."""
    product_id: int = Field(gt=0)
    confirmed_status: ObservationStatus


class ObservationRead(BaseModel):
    id: int
    shelf_id: int
    product_id: int | None
    source: str
    status: str
    confidence: float | None
    observed_quantity: float | None
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



class ProductEmbeddingExemplarCreate(BaseModel):
    product_id: int
    shelf_image_id: int | None = None
    embedding: list[float] = Field(min_length=1, max_length=4096)
    model_version: str = Field(min_length=1, max_length=100)
    image_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    licence: str = Field(min_length=1, max_length=250)

    @model_validator(mode="after")
    def embedding_must_be_valid(self):
        import math
        if any(not math.isfinite(value) for value in self.embedding):
            raise ValueError("embedding values must be finite")
        if not any(value != 0 for value in self.embedding):
            raise ValueError("embedding cannot be a zero vector")
        if not self.model_version.strip():
            raise ValueError("model_version cannot be blank")
        if not self.licence.strip():
            raise ValueError("licence cannot be blank")
        return self


class ProductEmbeddingExemplarReview(BaseModel):
    review_status: Literal["APPROVED", "REJECTED"]
    review_notes: str | None = Field(default=None, max_length=2000)


class ProductEmbeddingExemplarRead(BaseModel):
    id: int
    product_id: int
    shelf_image_id: int | None
    embedding_dimension: int
    model_version: str
    image_sha256: str
    licence: str
    review_status: Literal["PENDING", "APPROVED", "REJECTED"]
    created_by_user_id: int | None
    reviewed_by_user_id: int | None
    reviewed_at: datetime | None
    review_notes: str | None
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
    on_hand_quantity: float = Field(
        ge=0, le=999_999_999.999, allow_inf_nan=False
    )
    reserved_quantity: float = Field(
        default=0, ge=0, le=999_999_999.999, allow_inf_nan=False
    )
    source: InventorySource
    external_reference: str | None = Field(default=None, max_length=120)
    captured_at: datetime | None = None

    @field_validator("external_reference")
    @classmethod
    def validate_external_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("external_reference cannot be blank")
        if any(ord(character) < 32 or 127 <= ord(character) <= 159 for character in normalized):
            raise ValueError("external_reference cannot contain control characters")
        return normalized

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


class InventoryFreshnessPolicyUpsert(BaseModel):
    store_id: int
    source: InventorySource
    max_age_minutes: int = Field(ge=1, le=10080)


class InventoryFreshnessPolicyRead(BaseModel):
    id: int
    store_id: int
    source: InventorySource
    max_age_minutes: int
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class InventoryReconciliationCreate(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)


class InventoryMovementRead(BaseModel):
    id: int
    task_id: int
    store_id: int
    product_id: int
    movement_type: Literal["BACKROOM_TO_SHELF"]
    quantity: float
    source_snapshot_id: int
    result_snapshot_id: int
    actor_user_id: int
    reason: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


ReplenishmentStatus = Literal[
    "NEEDS_REPLENISHMENT",
    "BACKROOM_OUT_OF_STOCK",
    "INVENTORY_UNKNOWN",
    "STALE_OBSERVATION",
    "INVALID_OBSERVATION_TIMESTAMP",
    "STALE_INVENTORY",
    "INVALID_INVENTORY_TIMESTAMP",
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
    observed_shelf_quantity: float | None = None
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
    requested_quantity: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    notes: str | None = Field(default=None, max_length=2000)


class ReplenishmentTaskStatusUpdate(BaseModel):
    status: TaskStatus
    assigned_to: str | None = Field(default=None, min_length=1, max_length=120)
    assigned_user_id: int | None = None
    actual_quantity: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    exception_reason: str | None = Field(default=None, min_length=3, max_length=1000)


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
    actual_quantity: float | None
    exception_reason: str | None
    model_config = ConfigDict(from_attributes=True)


class ReplenishmentTaskEventRead(BaseModel):
    id: int
    task_id: int
    event_type: Literal["CREATED", "APPROVED", "STATUS_CHANGED", "INVENTORY_RECONCILED"]
    from_status: TaskStatus | None
    to_status: TaskStatus | None
    actor_user_id: int | None
    actual_quantity: float | None
    reason: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


ObservationAlertStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"]
ObservationAlertCondition = Literal["LOW_STOCK", "EMPTY", "MISPLACED", "DAMAGED"]


class ObservationAlertRead(BaseModel):
    id: int
    store_id: int
    shelf_id: int
    product_id: int
    condition: ObservationAlertCondition
    status: ObservationAlertStatus
    first_seen_at: datetime
    last_seen_at: datetime
    confirmation_count: int
    average_confidence: float
    sources: list[str]
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None
    resolution_reason: str | None
    resolved_by_user_id: int | None
    model_config = ConfigDict(from_attributes=True)


class ObservationAlertUpdate(BaseModel):
    status: Literal["ACKNOWLEDGED", "RESOLVED", "DISMISSED"]
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value):
        return value.strip() if value is not None else None

    @model_validator(mode="after")
    def require_resolution_reason(self):
        if self.status in {"RESOLVED", "DISMISSED"} and not self.reason:
            raise ValueError("A non-empty reason is required to resolve or dismiss an alert")
        return self


class ObservationAlertEventRead(BaseModel):
    id: int
    alert_id: int
    event_type: Literal["CREATED", "EVIDENCE_UPDATED", "ACKNOWLEDGED", "RESOLVED", "DISMISSED"]
    from_status: ObservationAlertStatus | None
    to_status: ObservationAlertStatus | None
    actor_user_id: int | None
    reason: str | None
    evidence: dict | None
    created_at: datetime
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


class StoreEmployeeRead(BaseModel):
    """Minimal employee identity returned to store supervisors for assignment."""
    id: int
    store_id: int | None
    full_name: str
    role: UserRole
    is_active: bool
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


class CaptureSessionCreate(BaseModel):
    shelf_id: int
    source_type: Literal["fixed_camera", "robot", "mobile"]
    source_device_id: str | None = Field(default=None, min_length=1, max_length=120)
    capture_mode: Literal["single", "burst", "video_sample"] = "single"
    started_at: datetime | None = None


class CaptureSessionRead(BaseModel):
    id: int
    store_id: int
    shelf_id: int
    source_type: str
    source_device_id: str | None
    capture_mode: str
    started_at: datetime
    ended_at: datetime | None
    created_by_user_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfImageRead(BaseModel):
    id: int
    shelf_id: int
    capture_session_id: int | None = None
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
    retention_status: Literal["ACTIVE", "RESTRICTED", "PENDING_PURGE", "PURGED"] = "ACTIVE"
    retention_requested_at: datetime | None = None
    retention_requested_by_user_id: int | None = None
    retention_reason: str | None = None
    legal_hold: bool = False
    purge_not_before: datetime | None = None
    purged_at: datetime | None = None
    retention_policy_version: str | None = None
    model_config = ConfigDict(from_attributes=True)


class ShelfImageRetentionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("A retention reason must contain at least 3 non-whitespace characters")
        return normalized


ArtifactType = Literal["DATASET_COPY", "DATASET_RELEASE", "CROP", "REPORT", "BACKUP", "CACHE", "OBJECT_REPLICA", "OTHER"]


class StoreExternalIntegrationCreate(BaseModel):
    external_system: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=120)
    required_for_retention: bool = False
    capabilities: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("external_system", "provider")
    @classmethod
    def normalize_integration_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Integration identity cannot be blank")
        return normalized

    @field_validator("capabilities")
    @classmethod
    def normalize_integration_capabilities(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Integration capabilities cannot be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Integration capabilities cannot contain duplicates")
        return normalized


class StoreExternalIntegrationUpdate(BaseModel):
    status: Literal["ACTIVE", "REVOKED"] | None = None
    required_for_retention: bool | None = None
    capabilities: list[str] | None = Field(default=None, max_length=30)

    @field_validator("capabilities")
    @classmethod
    def normalize_updated_capabilities(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("Integration capabilities must be non-blank and unique")
        return normalized

    @model_validator(mode="after")
    def require_an_update(self):
        if not self.model_fields_set:
            raise ValueError("At least one integration setting must be supplied")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Integration settings cannot be explicitly null")
        return self


class StoreExternalIntegrationRead(BaseModel):
    id: int
    store_id: int
    external_system: str
    provider: str
    status: Literal["ACTIVE", "REVOKED"]
    required_for_retention: bool
    capabilities: list[str]
    last_seen_at: datetime | None
    created_by_user_id: int
    updated_by_user_id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class StoreExternalIntegrationCoverageRead(BaseModel):
    store_id: int
    coverage_configured: bool
    coverage_complete: bool
    required_integrations: int
    active_required_integrations: int
    missing_or_revoked_integrations: list[str]
    never_seen_integrations: list[str]
    stale_integrations: list[str]
    checked_at: datetime


class ShelfImageArtifactReferenceCreate(BaseModel):
    artifact_type: ArtifactType
    external_system: str = Field(min_length=1, max_length=120)
    external_reference: str = Field(min_length=1, max_length=500)
    parent_reference_id: int | None = Field(default=None, gt=0, strict=True)
    release_id: str | None = Field(default=None, max_length=160)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("external_system", "external_reference")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized


class ShelfImageArtifactReferenceRead(BaseModel):
    id: int
    shelf_image_id: int
    store_id: int
    artifact_type: ArtifactType
    external_system: str
    external_reference: str
    parent_reference_id: int | None
    release_id: str | None
    sha256: str | None
    declared_by_user_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


ArtifactDispositionAction = Literal["PROPOSE", "APPROVE", "REJECT", "ATTEST_DISPOSED"]


class ShelfImageArtifactDispositionActionRequest(BaseModel):
    action: ArtifactDispositionAction
    reason: str = Field(min_length=3, max_length=2000)
    evidence_reference: str | None = Field(default=None, min_length=1, max_length=500)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("reason")
    @classmethod
    def normalize_disposition_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("A meaningful disposition reason is required")
        return normalized

    @field_validator("evidence_reference")
    @classmethod
    def normalize_evidence_reference(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("Evidence reference cannot be blank")
        return normalized


ArtifactInventoryState = Literal["PRESENT", "ABSENT"]


class ShelfImageArtifactInventoryEntryCreate(BaseModel):
    artifact_type: ArtifactType
    external_reference: str = Field(min_length=1, max_length=500)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    state: ArtifactInventoryState

    @field_validator("external_reference")
    @classmethod
    def normalize_inventory_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Inventory external_reference cannot be blank")
        return normalized


class ShelfImageArtifactInventorySnapshotCreate(BaseModel):
    external_system: str = Field(min_length=1, max_length=120)
    snapshot_id: str = Field(min_length=1, max_length=160)
    generated_at: datetime
    inventory_complete: Literal[True]
    entries: list[ShelfImageArtifactInventoryEntryCreate] = Field(min_length=1, max_length=5000)
    key_id: str = Field(default="legacy", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("external_system", "snapshot_id")
    @classmethod
    def normalize_inventory_identity(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Inventory identity cannot be blank")
        return normalized

    @field_validator("generated_at")
    @classmethod
    def require_inventory_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Inventory generated_at must include a timezone")
        return value

    @model_validator(mode="after")
    def reject_duplicate_inventory_entries(self):
        identities = [
            (entry.artifact_type, entry.external_reference)
            for entry in self.entries
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("Inventory entries cannot contain duplicate artifact identities")
        return self


class ShelfImageArtifactInventorySnapshotRead(BaseModel):
    id: int
    shelf_image_id: int
    store_id: int
    external_system: str
    snapshot_id: str
    generated_at: datetime
    inventory_complete: bool
    manifest_sha256: str
    source_signature: str
    key_id: str
    inventory_manifest: list[dict]
    artifact_count: int
    present_count: int
    absent_count: int
    verified_at: datetime
    created_by_user_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfImageArtifactDispositionEventRead(BaseModel):
    id: int
    sequence_number: int
    artifact_reference_id: int
    shelf_image_id: int
    store_id: int
    event_type: Literal["PROPOSED", "APPROVED", "REJECTED", "DISPOSAL_ATTESTED"]
    actor_user_id: int
    evidence_reference: str | None
    evidence_sha256: str | None
    reason: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfImagePurgeScheduleRequest(BaseModel):
    purge_not_before: datetime
    policy_version: str = Field(min_length=1, max_length=40)
    reason: str = Field(min_length=3, max_length=2000)

    @field_validator("policy_version", "reason")
    @classmethod
    def normalize_retention_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Retention policy metadata cannot be blank")
        return normalized

    @field_validator("purge_not_before")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("purge_not_before must include a timezone")
        return value


class ShelfImageRetentionEventRead(BaseModel):
    id: int
    shelf_image_id: int
    event_type: Literal["RESTRICTED", "RESTORED", "LEGAL_HOLD_APPLIED", "LEGAL_HOLD_RELEASED", "PURGE_SCHEDULED", "PURGE_CANCELLED"]
    from_status: str
    to_status: str
    actor_user_id: int | None
    reason: str
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
    embedding_model_version: str | None
    sku_match_status: Literal["MATCHED", "AMBIGUOUS", "UNKNOWN"]
    sku_similarity: float | None
    sku_match_margin: float | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class DetectionSkuReviewCreate(BaseModel):
    decision: Literal["CONFIRMED", "CORRECTED", "REJECTED"]
    selected_product_id: int | None = None
    notes: str | None = Field(default=None, max_length=2000)


class DetectionSkuReviewRead(BaseModel):
    id: int
    detection_id: int
    previous_product_id: int | None
    selected_product_id: int | None
    decision: Literal["CONFIRMED", "CORRECTED", "REJECTED"]
    reviewer_user_id: int | None
    notes: str | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfImageOCREvidenceInput(BaseModel):
    detection_id: int | None = None
    text: str = Field(min_length=1, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(gt=0, le=1)
    y_max: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def validate_box(self):
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("OCR region coordinates must be ordered")
        return self


class ShelfImageOCRRunCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    model_version: str = Field(min_length=1, max_length=120)
    regions: list[ShelfImageOCREvidenceInput] = Field(max_length=1000)


class ShelfImageOCRRunRead(BaseModel):
    id: int
    shelf_image_id: int
    provider: str
    model_version: str
    status: Literal["COMPLETED", "FAILED"]
    created_by_user_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfImageOCREvidenceRead(BaseModel):
    id: int
    run_id: int
    detection_id: int | None
    text: str
    normalized_text: str
    confidence: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    association_status: Literal["ASSIGNED", "UNASSIGNED"]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfImageOCRMatchRead(BaseModel):
    id: int
    run_id: int
    detection_id: int
    suggested_product_id: int | None
    observed_text: str
    ocr_confidence: float
    status: Literal["SUGGESTED", "AMBIGUOUS", "UNKNOWN"]
    top_score: float | None
    margin: float | None
    candidates: list[dict]
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfImageFusedEvidenceRead(BaseModel):
    id: int
    ocr_run_id: int
    detection_id: int
    status: Literal["CONSENSUS", "VISUAL_ONLY", "TEXT_ONLY", "CONFLICT", "AMBIGUOUS", "UNKNOWN"]
    suggested_product_id: int | None
    visual_product_id: int | None
    text_product_id: int | None
    visual_status: str
    text_status: str
    visual_similarity: float | None
    text_score: float | None
    ocr_confidence: float | None
    visual_model_version: str | None
    ocr_provider: str
    ocr_model_version: str
    reason: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfImageTrainingCandidateRead(BaseModel):
    review_id: int
    detection_id: int
    shelf_image_id: int
    store_id: int
    shelf_id: int
    product_id: int
    sku: str
    product_name: str
    decision: Literal["CONFIRMED", "CORRECTED"]
    reviewed_at: datetime
    image_sha256: str
    captured_at: datetime
    capture_group_key: str
    capture_session_id: int | None = None
    bbox: dict[str, float]
    detector_model_version: str
    embedding_model_version: str | None
    dataset_status: Literal["CANDIDATE"]
    split_policy: str
    requires_exemplar_approval: bool


class ShelfImageReviewQueueItem(BaseModel):
    fused_evidence_id: int
    detection_id: int
    shelf_image_id: int
    shelf_id: int
    shelf_code: str
    image_filename: str
    status: Literal["CONSENSUS", "VISUAL_ONLY", "TEXT_ONLY", "CONFLICT", "AMBIGUOUS", "UNKNOWN"]
    suggested_product_id: int | None
    visual_product_id: int | None
    text_product_id: int | None
    detection_label: str
    detection_confidence: float
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    visual_similarity: float | None
    text_score: float | None
    ocr_confidence: float | None
    visual_model_version: str | None
    ocr_provider: str
    ocr_model_version: str
    reason: str
    created_at: datetime


SalesSource = Literal["POS", "ERP", "MANUAL", "IMPORT"]


class DailySalesRecordCreate(BaseModel):
    store_id: int
    product_id: int
    sales_date: date
    quantity: float = Field(ge=0, allow_inf_nan=False)
    source: SalesSource
    external_reference: str = Field(min_length=1, max_length=120)


class DailySalesRecordRead(BaseModel):
    id: int
    store_id: int
    product_id: int
    sales_date: date
    quantity: float
    source: SalesSource
    external_reference: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class HourlySalesRecordCreate(BaseModel):
    store_id: int
    product_id: int
    business_date: date
    hour_of_day: int = Field(ge=0, le=23)
    quantity: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)
    source: SalesSource
    external_reference: str = Field(min_length=1, max_length=120)


class HourlySalesRecordRead(HourlySalesRecordCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class HourlyStoreTrafficRecordCreate(BaseModel):
    store_id: int
    business_date: date
    hour_of_day: int = Field(ge=0, le=23)
    customer_count: int = Field(ge=0, le=2_000_000)
    source: SalesSource
    external_reference: str = Field(min_length=1, max_length=120)


class HourlyStoreTrafficRecordRead(HourlyStoreTrafficRecordCreate):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class HourlySalesBatchCreate(BaseModel):
    records: list[HourlySalesRecordCreate] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_external_keys(self):
        keys = [(r.store_id, r.product_id, r.business_date, r.hour_of_day, r.source, r.external_reference) for r in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("Batch contains duplicate hourly sales external keys")
        if len({r.store_id for r in self.records}) != 1:
            raise ValueError("A batch must contain records for exactly one store")
        return self


class HourlyStoreTrafficBatchCreate(BaseModel):
    records: list[HourlyStoreTrafficRecordCreate] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def unique_external_keys(self):
        keys = [(r.store_id, r.business_date, r.hour_of_day, r.source, r.external_reference) for r in self.records]
        if len(keys) != len(set(keys)):
            raise ValueError("Batch contains duplicate hourly traffic external keys")
        if len({r.store_id for r in self.records}) != 1:
            raise ValueError("A batch must contain records for exactly one store")
        return self



WarehouseTemperature = Literal["AMBIENT", "CHILLED", "FROZEN"]


class WarehouseLocationCreate(BaseModel):
    store_id: int
    code: str = Field(min_length=1, max_length=80)
    aisle: str | None = Field(default=None, max_length=40)
    rack: str | None = Field(default=None, max_length=40)
    bin_code: str | None = Field(default=None, max_length=40)
    distance_to_picking_m: float = Field(ge=0, le=100000)
    max_volume_cm3: float = Field(gt=0, le=1_000_000_000)
    max_weight_kg: float = Field(gt=0, le=1_000_000)
    temperature_zone: WarehouseTemperature = "AMBIENT"


class WarehouseProductProfileCreate(BaseModel):
    product_id: int
    unit_volume_cm3: float = Field(gt=0, le=1_000_000_000)
    unit_weight_kg: float = Field(gt=0, le=1_000_000)
    temperature_requirement: WarehouseTemperature = "AMBIENT"
    is_fragile: bool = False
    requires_segregation: bool = False


class WarehousePlacementCreate(BaseModel):
    location_id: int
    product_id: int
    quantity: float = Field(ge=0, le=1_000_000_000)


PackagingType = Literal["UNIT", "CASE", "PALLET", "OTHER"]


class ProductPackagingLevelCreate(BaseModel):
    product_id: int
    code: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=100)
    package_type: PackagingType
    base_units_per_package: float = Field(gt=0, le=1_000_000_000, allow_inf_nan=False)
    barcode: str | None = Field(default=None, max_length=80)
    gross_weight_kg: float | None = Field(default=None, gt=0, le=1_000_000, allow_inf_nan=False)
    package_volume_cm3: float | None = Field(default=None, gt=0, le=1_000_000_000, allow_inf_nan=False)
    is_ordering_unit: bool = False
    is_replenishment_unit: bool = False


class ReplenishmentPackCalculationRequest(BaseModel):
    required_base_units: float = Field(gt=0, le=1_000_000_000, allow_inf_nan=False)
    packaging_code: str = Field(min_length=1, max_length=40)
    allow_open_package: bool = False


PalletStatus = Literal["READY", "ON_DISPLAY", "PARTIAL", "RETURNED", "REBUILDING", "EMPTY", "QUARANTINED"]
PalletLocationType = Literal["WAREHOUSE", "PREPARATION", "SALES_FLOOR", "OTHER"]


class StorePalletCreate(BaseModel):
    store_id: int
    product_id: int
    packaging_level_id: int
    pallet_code: str = Field(min_length=1, max_length=100)
    lot_code: str | None = Field(default=None, max_length=100)
    expiry_date: date | None = None
    base_quantity: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)
    status: PalletStatus = "READY"
    location_type: PalletLocationType = "WAREHOUSE"
    location_code: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_initial_state(self):
        if self.status == "EMPTY" and self.base_quantity != 0:
            raise ValueError("EMPTY pallets must have zero base quantity")
        if self.status != "EMPTY" and self.base_quantity <= 0:
            raise ValueError("Non-empty pallet statuses require positive base quantity")
        if self.status == "ON_DISPLAY" and self.location_type != "SALES_FLOOR":
            raise ValueError("ON_DISPLAY pallets must have SALES_FLOOR location type")
        if self.status in {"READY", "RETURNED", "REBUILDING"} and self.location_type == "SALES_FLOOR":
            raise ValueError("This pallet status is incompatible with SALES_FLOOR location")
        return self


class StorePalletRead(BaseModel):
    id: int
    store_id: int
    product_id: int
    packaging_level_id: int
    pallet_code: str
    lot_code: str | None
    expiry_date: date | None
    base_quantity: float
    status: PalletStatus
    location_type: PalletLocationType
    location_code: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PalletRotationPolicyCreate(BaseModel):
    store_id: int
    product_id: int
    threshold_ratio: float = Field(default=0.5, gt=0, le=1, allow_inf_nan=False)
    is_enabled: bool = True


class PalletRotationPolicyRead(BaseModel):
    id: int
    store_id: int
    product_id: int
    threshold_ratio: float
    is_enabled: bool
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PalletRotationSimulationRequest(BaseModel):
    store_id: int
    pallet_id: int
    traffic_level: Literal["HIGH", "LOW", "UNKNOWN"]
    backroom_capacity_available: bool
    conventional_replenishment_minutes: float = Field(ge=0, le=1440, allow_inf_nan=False)
    pallet_swap_minutes: float = Field(ge=0, le=1440, allow_inf_nan=False)
    transport_minutes: float = Field(ge=0, le=1440, allow_inf_nan=False)
    pallet_rebuild_minutes: float = Field(ge=0, le=1440, allow_inf_nan=False)
    labour_cost_per_hour: float = Field(gt=0, le=10000, allow_inf_nan=False)
    forecast_consumption_until_low_traffic: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)


class PalletLifecycleUpdate(BaseModel):
    expected_status: PalletStatus
    expected_base_quantity: float = Field(ge=0, le=1_000_000_000, allow_inf_nan=False)
    status: PalletStatus | None = None
    base_quantity: float | None = Field(default=None, ge=0, le=1_000_000_000, allow_inf_nan=False)
    location_type: PalletLocationType | None = None
    location_code: str | None = Field(default=None, max_length=100)
    reason: str = Field(min_length=3, max_length=1000)

    @model_validator(mode="after")
    def validate_change(self):
        if all(getattr(self, field) is None for field in ("status", "base_quantity", "location_type", "location_code")):
            raise ValueError("At least one pallet field must change")
        return self


class PalletRotationEventRead(BaseModel):
    id: int
    pallet_id: int
    event_type: str
    from_location_type: str | None
    from_location_code: str | None
    to_location_type: str | None
    to_location_code: str | None
    quantity_before: float
    quantity_after: float
    lot_code: str | None
    expiry_date: date | None
    reason: str | None
    performed_by_user_id: int | None
    occurred_at: datetime
    model_config = ConfigDict(from_attributes=True)


class PalletRotationPolicyUpdate(BaseModel):
    threshold_ratio: float | None = Field(default=None, gt=0, le=1, allow_inf_nan=False)
    is_enabled: bool | None = None

    @model_validator(mode="after")
    def require_at_least_one_change(self):
        if self.threshold_ratio is None and self.is_enabled is None:
            raise ValueError("At least one policy field must be supplied")
        if "threshold_ratio" in self.model_fields_set and self.threshold_ratio is None:
            raise ValueError("threshold_ratio cannot be null")
        if "is_enabled" in self.model_fields_set and self.is_enabled is None:
            raise ValueError("is_enabled cannot be null")
        return self



class ShelfPlanogramCellCreate(BaseModel):
    cell_code: str = Field(min_length=1, max_length=80)
    row_index: int = Field(ge=0, le=10_000)
    column_index: int = Field(ge=0, le=10_000)
    x_min: float = Field(ge=0, le=1, allow_inf_nan=False)
    y_min: float = Field(ge=0, le=1, allow_inf_nan=False)
    x_max: float = Field(ge=0, le=1, allow_inf_nan=False)
    y_max: float = Field(ge=0, le=1, allow_inf_nan=False)
    expected_product_id: int | None = Field(default=None, gt=0)
    expected_facings: int | None = Field(default=None, gt=0, le=500)

    @model_validator(mode="after")
    def validate_geometry(self):
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("Cell bounds must have positive width and height")
        if self.expected_facings is not None and self.expected_product_id is None:
            raise ValueError("expected_facings requires expected_product_id")
        return self


class ShelfPlanogramCreate(BaseModel):
    calibration_source: Literal["MANUAL", "IMAGE"] = "MANUAL"
    calibration_image_id: int | None = Field(default=None, gt=0)
    calibration_image_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    cells: list[ShelfPlanogramCellCreate] = Field(min_length=1, max_length=500)


class ShelfPlanogramCellsReplace(BaseModel):
    cells: list[ShelfPlanogramCellCreate] = Field(min_length=1, max_length=500)


class ShelfPlanogramLifecycleRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ShelfPlanogramCellRead(BaseModel):
    id: int
    planogram_id: int
    cell_code: str
    row_index: int
    column_index: int
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    expected_product_id: int | None
    expected_facings: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ShelfPlanogramRead(BaseModel):
    id: int
    shelf_id: int
    version: int
    status: Literal["DRAFT", "ACTIVE", "RETIRED"]
    calibration_source: Literal["MANUAL", "IMAGE"]
    calibration_image_id: int | None
    calibration_image_sha256: str | None
    created_by_user_id: int
    created_at: datetime
    activated_by_user_id: int | None
    activated_at: datetime | None
    activation_reason: str | None
    retired_by_user_id: int | None
    retired_at: datetime | None
    retirement_reason: str | None
    cells: list[ShelfPlanogramCellRead]
    model_config = ConfigDict(from_attributes=True)


class ShelfPlanogramCellComparisonRead(BaseModel):
    cell_code: str
    status: Literal[
        "UNKNOWN", "EMPTY", "CONFLICT", "MISPLACED",
        "OCCUPIED_UNIDENTIFIED", "UNDER_FACED", "OVER_FACED", "OCCUPIED",
    ]
    expected_product_id: int | None
    expected_facings: int | None
    observed_facings: int
    observed_product_ids: list[int | None]
    detection_ids: list[int]
    overlap_ratio: float = Field(ge=0, le=1)


class ShelfPlanogramComparisonRead(BaseModel):
    comparison_schema_version: int
    comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shelf_image_id: int
    shelf_id: int
    image_sha256: str
    model_version: str | None
    planogram_id: int
    planogram_version: int
    calibration_source: Literal["MANUAL", "IMAGE"]
    calibration_image_id: int | None
    calibration_image_sha256: str | None
    cells: list[ShelfPlanogramCellComparisonRead]

class EmployeeShiftCreate(BaseModel):
    store_id: int
    employee_id: int
    starts_at: datetime
    ends_at: datetime
    break_minutes: int = Field(default=0, ge=0, le=720)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_shift_window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at tem de ser posterior a starts_at")
        if (self.ends_at - self.starts_at).total_seconds() < self.break_minutes * 60:
            raise ValueError("A pausa não pode exceder a duração do turno")
        return self


class EmployeeShiftRead(BaseModel):
    id: int
    store_id: int
    employee_id: int
    starts_at: datetime
    ends_at: datetime
    break_minutes: int
    status: Literal["SCHEDULED", "CANCELLED"]
    notes: str | None
    created_by_user_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EmployeeSkillCreate(BaseModel):
    store_id: int
    employee_id: int
    skill_code: str = Field(min_length=2, max_length=60, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    level: int = Field(default=1, ge=1, le=5)


class EmployeeSkillRead(BaseModel):
    id: int
    store_id: int
    employee_id: int
    skill_code: str
    level: int
    created_by_user_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class EmployeeAvailabilityCreate(BaseModel):
    store_id: int
    employee_id: int
    starts_at: datetime
    ends_at: datetime
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_availability_window(self):
        if self.ends_at <= self.starts_at:
            raise ValueError("ends_at tem de ser posterior a starts_at")
        return self


class EmployeeAvailabilityRead(BaseModel):
    id: int
    store_id: int
    employee_id: int
    starts_at: datetime
    ends_at: datetime
    status: Literal["AVAILABLE", "UNAVAILABLE"]
    reason: str | None
    created_by_user_id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

