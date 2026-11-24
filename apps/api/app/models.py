from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text, Float, Integer, Boolean, Numeric, UniqueConstraint, CheckConstraint, ForeignKeyConstraint, Index, BigInteger, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    zones: Mapped[list["Zone"]] = relationship(back_populates="store", cascade="all, delete-orphan")


class StoreExternalIntegration(Base):
    """Store-scoped allow-list and operational policy for an external system."""
    __tablename__ = "store_external_integrations"
    __table_args__ = (
        UniqueConstraint("store_id", "external_system", name="uq_store_external_integration_system"),
        CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_store_external_integration_status"),
        Index("ix_store_external_integrations_store_status", "store_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    external_system: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE", nullable=False)
    required_for_retention: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    capabilities: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Zone(Base):
    __tablename__ = "zones"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    store: Mapped[Store] = relationship(back_populates="zones")
    shelves: Mapped[list["Shelf"]] = relationship(back_populates="zone", cascade="all, delete-orphan")


class Shelf(Base):
    __tablename__ = "shelves"
    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str | None] = mapped_column(String(250), nullable=True)
    zone: Mapped[Zone] = relationship(back_populates="shelves")
    observations: Mapped[list["Observation"]] = relationship(back_populates="shelf", cascade="all, delete-orphan")
    product_links: Mapped[list["ShelfProduct"]] = relationship(back_populates="shelf", cascade="all, delete-orphan")


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (
        CheckConstraint("observed_quantity IS NULL OR observed_quantity >= 0", name="ck_observation_quantity_nonnegative"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    shelf_id: Mapped[int] = mapped_column(ForeignKey("shelves.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(30), default="mobile")
    status: Mapped[str] = mapped_column(String(30), default="UNKNOWN", index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    observed_quantity: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    shelf: Mapped[Shelf] = relationship(back_populates="observations")
    product: Mapped["Product | None"] = relationship(back_populates="observations")


class ObservationAlert(Base):
    """Persisted, deduplicated alert derived from repeated SKU-attributed evidence."""
    __tablename__ = "observation_alerts"
    __table_args__ = (
        CheckConstraint("condition IN ('LOW_STOCK', 'EMPTY', 'MISPLACED', 'DAMAGED')", name="ck_observation_alert_condition"),
        CheckConstraint("status IN ('OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'DISMISSED')", name="ck_observation_alert_status"),
        CheckConstraint("confirmation_count >= 2", name="ck_observation_alert_confirmations"),
        CheckConstraint("average_confidence >= 0 AND average_confidence <= 1", name="ck_observation_alert_confidence"),
        Index(
            "uq_observation_alert_active_scope",
            "store_id", "shelf_id", "product_id", "condition",
            unique=True,
            postgresql_where=text("status IN ('OPEN', 'ACKNOWLEDGED')"),
            sqlite_where=text("status IN ('OPEN', 'ACKNOWLEDGED')"),
        ),
        Index("ix_observation_alert_store_status_created", "store_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    shelf_id: Mapped[int] = mapped_column(ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    condition: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", nullable=False, index=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    average_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    sources: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class ObservationAlertEvent(Base):
    """Append-only audit trail for alert creation, evidence refresh and human decisions."""
    __tablename__ = "observation_alert_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('CREATED', 'EVIDENCE_UPDATED', 'ACKNOWLEDGED', 'RESOLVED', 'DISMISSED')", name="ck_observation_alert_event_type"),
        Index("ix_observation_alert_events_alert_created", "alert_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("observation_alerts.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    brand: Mapped[str | None] = mapped_column(String(120), nullable=True)
    unit: Mapped[str] = mapped_column(String(30), default="un")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    shelf_links: Mapped[list["ShelfProduct"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    observations: Mapped[list["Observation"]] = relationship(back_populates="product")



class ProductEmbeddingExemplar(Base):
    """Reviewed reference embedding used for conservative SKU matching."""
    __tablename__ = "product_embedding_exemplars"
    __table_args__ = (
        UniqueConstraint("product_id", "model_version", "image_sha256",
                         name="uq_product_embedding_product_model_image"),
        CheckConstraint("review_status IN ('PENDING', 'APPROVED', 'REJECTED')",
                        name="ck_product_embedding_review_status"),
        CheckConstraint("length(image_sha256) = 64",
                        name="ck_product_embedding_image_sha256_length"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    shelf_image_id: Mapped[int | None] = mapped_column(ForeignKey("shelf_images.id", ondelete="SET NULL"), nullable=True, index=True)
    embedding: Mapped[list] = mapped_column(JSON, nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    image_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    licence: Mapped[str] = mapped_column(String(250), nullable=False)
    review_status: Mapped[str] = mapped_column(String(12), default="PENDING", nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ShelfProduct(Base):
    __tablename__ = "shelf_products"
    __table_args__ = (
        UniqueConstraint("shelf_id", "product_id", name="uq_shelf_products_shelf_product"),
        CheckConstraint("target_quantity > 0", name="ck_shelf_products_target_quantity_positive"),
        CheckConstraint("min_display_quantity >= 0", name="ck_shelf_products_min_display_nonnegative"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    shelf_id: Mapped[int] = mapped_column(ForeignKey("shelves.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    target_quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    min_display_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position: Mapped[str | None] = mapped_column(String(80), nullable=True)
    shelf: Mapped[Shelf] = relationship(back_populates="product_links")
    product: Mapped[Product] = relationship(back_populates="shelf_links")


class ShelfPlanogram(Base):
    """Versioned, human-calibrated geometry for one physical shelf."""

    __tablename__ = "shelf_planograms"
    __table_args__ = (
        UniqueConstraint("shelf_id", "version", name="uq_shelf_planogram_shelf_version"),
        CheckConstraint("version > 0", name="ck_shelf_planogram_version_positive"),
        CheckConstraint("status IN ('DRAFT', 'ACTIVE', 'RETIRED')", name="ck_shelf_planogram_status"),
        CheckConstraint("calibration_source IN ('MANUAL', 'IMAGE')", name="ck_shelf_planogram_calibration_source"),
        CheckConstraint(
            "(calibration_source = 'MANUAL' AND calibration_image_id IS NULL AND calibration_image_sha256 IS NULL) "
            "OR (calibration_source = 'IMAGE' AND calibration_image_id IS NOT NULL AND length(calibration_image_sha256) = 64)",
            name="ck_shelf_planogram_calibration_reference",
        ),
        CheckConstraint(
            "(activated_by_user_id IS NULL AND activated_at IS NULL AND activation_reason IS NULL) "
            "OR (activated_by_user_id IS NOT NULL AND activated_at IS NOT NULL AND activation_reason IS NOT NULL AND length(trim(activation_reason)) > 0)",
            name="ck_shelf_planogram_activation_metadata",
        ),
        CheckConstraint(
            "(retired_by_user_id IS NULL AND retired_at IS NULL AND retirement_reason IS NULL) "
            "OR (retired_by_user_id IS NOT NULL AND retired_at IS NOT NULL AND retirement_reason IS NOT NULL AND length(trim(retirement_reason)) > 0)",
            name="ck_shelf_planogram_retirement_metadata",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND activated_at IS NULL AND retired_at IS NULL) "
            "OR (status = 'ACTIVE' AND activated_at IS NOT NULL AND retired_at IS NULL) "
            "OR (status = 'RETIRED' AND activated_at IS NOT NULL AND retired_at IS NOT NULL)",
            name="ck_shelf_planogram_status_timestamps",
        ),
        CheckConstraint("activated_at IS NULL OR activated_at >= created_at", name="ck_shelf_planogram_activation_after_creation"),
        CheckConstraint("retired_at IS NULL OR retired_at >= activated_at", name="ck_shelf_planogram_retirement_after_activation"),
        Index(
            "uq_shelf_planogram_one_active_per_shelf",
            "shelf_id",
            unique=True,
            sqlite_where=text("status = 'ACTIVE'"),
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        Index("ix_shelf_planograms_shelf_status_version", "shelf_id", "status", "version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shelf_id: Mapped[int] = mapped_column(ForeignKey("shelves.id", ondelete="RESTRICT"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="DRAFT", nullable=False, index=True)
    calibration_source: Mapped[str] = mapped_column(String(8), default="MANUAL", nullable=False)
    calibration_image_id: Mapped[int | None] = mapped_column(
        ForeignKey("shelf_images.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    calibration_image_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    activated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activation_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retired_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retirement_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cells: Mapped[list["ShelfPlanogramCell"]] = relationship(
        back_populates="planogram", cascade="all, delete-orphan", order_by="ShelfPlanogramCell.row_index, ShelfPlanogramCell.column_index"
    )


class ShelfPlanogramCell(Base):
    """One expected facing position in a versioned shelf planogram."""

    __tablename__ = "shelf_planogram_cells"
    __table_args__ = (
        UniqueConstraint("planogram_id", "cell_code", name="uq_shelf_planogram_cell_code"),
        UniqueConstraint("planogram_id", "row_index", "column_index", name="uq_shelf_planogram_cell_grid_position"),
        CheckConstraint("row_index >= 0 AND column_index >= 0", name="ck_shelf_planogram_cell_grid_nonnegative"),
        CheckConstraint("length(trim(cell_code)) > 0", name="ck_shelf_planogram_cell_code_nonempty"),
        CheckConstraint(
            "x_min >= 0 AND x_min < x_max AND x_max <= 1 "
            "AND y_min >= 0 AND y_min < y_max AND y_max <= 1",
            name="ck_shelf_planogram_cell_bbox_normalized",
        ),
        CheckConstraint(
            "expected_facings IS NULL OR (expected_facings > 0 AND expected_product_id IS NOT NULL)",
            name="ck_shelf_planogram_cell_expected_facings",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    planogram_id: Mapped[int] = mapped_column(
        ForeignKey("shelf_planograms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cell_code: Mapped[str] = mapped_column(String(80), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    x_min: Mapped[float] = mapped_column(Float, nullable=False)
    y_min: Mapped[float] = mapped_column(Float, nullable=False)
    x_max: Mapped[float] = mapped_column(Float, nullable=False)
    y_max: Mapped[float] = mapped_column(Float, nullable=False)
    expected_product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    expected_facings: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    planogram: Mapped[ShelfPlanogram] = relationship(back_populates="cells")


class WarehouseLocation(Base):
    """Physical warehouse bin with measurable capacity and picking distance."""
    __tablename__ = "warehouse_locations"
    __table_args__ = (
        UniqueConstraint("store_id", "code", name="uq_warehouse_location_store_code"),
        CheckConstraint("distance_to_picking_m >= 0", name="ck_warehouse_location_distance_nonnegative"),
        CheckConstraint("max_volume_cm3 > 0", name="ck_warehouse_location_volume_positive"),
        CheckConstraint("max_weight_kg > 0", name="ck_warehouse_location_weight_positive"),
        CheckConstraint("temperature_zone IN ('AMBIENT', 'CHILLED', 'FROZEN')", name="ck_warehouse_location_temperature"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    aisle: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rack: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bin_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    distance_to_picking_m: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    max_volume_cm3: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    max_weight_kg: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    temperature_zone: Mapped[str] = mapped_column(String(12), default="AMBIENT", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class WarehouseProductProfile(Base):
    """Physical and handling constraints required by a product."""
    __tablename__ = "warehouse_product_profiles"
    __table_args__ = (
        UniqueConstraint("product_id", name="uq_warehouse_product_profile_product"),
        CheckConstraint("unit_volume_cm3 > 0", name="ck_warehouse_product_volume_positive"),
        CheckConstraint("unit_weight_kg > 0", name="ck_warehouse_product_weight_positive"),
        CheckConstraint("temperature_requirement IN ('AMBIENT', 'CHILLED', 'FROZEN')", name="ck_warehouse_product_temperature"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    unit_volume_cm3: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    unit_weight_kg: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False)
    temperature_requirement: Mapped[str] = mapped_column(String(12), default="AMBIENT", nullable=False)
    is_fragile: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_segregation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class WarehouseProductPlacement(Base):
    """Current quantity of a product held in a warehouse location."""
    __tablename__ = "warehouse_product_placements"
    __table_args__ = (
        UniqueConstraint("location_id", "product_id", name="uq_warehouse_placement_location_product"),
        CheckConstraint("quantity >= 0", name="ck_warehouse_placement_quantity_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    location_id: Mapped[int] = mapped_column(ForeignKey("warehouse_locations.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ProductPackagingLevel(Base):
    """A logistics packaging level expressed in the product base unit, independent of sales unit."""
    __tablename__ = "product_packaging_levels"
    __table_args__ = (
        UniqueConstraint("product_id", "code", name="uq_product_packaging_product_code"),
        Index(
            "uq_product_packaging_active_ordering_unit",
            "product_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE AND is_ordering_unit IS TRUE"),
            sqlite_where=text("is_active IS TRUE AND is_ordering_unit IS TRUE"),
        ),
        Index(
            "uq_product_packaging_active_replenishment_unit",
            "product_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE AND is_replenishment_unit IS TRUE"),
            sqlite_where=text("is_active IS TRUE AND is_replenishment_unit IS TRUE"),
        ),
        CheckConstraint("base_units_per_package > 0", name="ck_packaging_base_units_positive"),
        CheckConstraint("package_type IN ('UNIT', 'CASE', 'PALLET', 'OTHER')", name="ck_packaging_type"),
        CheckConstraint("gross_weight_kg IS NULL OR gross_weight_kg > 0", name="ck_packaging_weight_positive"),
        CheckConstraint("package_volume_cm3 IS NULL OR package_volume_cm3 > 0", name="ck_packaging_volume_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    package_type: Mapped[str] = mapped_column(String(12), nullable=False)
    base_units_per_package: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(80), nullable=True)
    gross_weight_kg: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    package_volume_cm3: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    is_ordering_unit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_replenishment_unit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class HourlySalesRecord(Base):
    """Immutable product sales aggregate for one local store-hour."""
    __tablename__ = "hourly_sales_records"
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", "business_date", "hour_of_day", "source", "external_reference",
                         name="uq_hourly_sales_external_reference"),
        CheckConstraint("quantity >= 0", name="ck_hourly_sales_quantity_nonnegative"),
        CheckConstraint("hour_of_day >= 0 AND hour_of_day <= 23", name="ck_hourly_sales_hour_range"),
        CheckConstraint("source IN ('POS', 'ERP', 'MANUAL', 'IMPORT')", name="ck_hourly_sales_source"),
        Index("ix_hourly_sales_store_product_date_hour", "store_id", "product_id", "business_date", "hour_of_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hour_of_day: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class HourlyStoreTrafficRecord(Base):
    """Immutable store customer-count aggregate for one local store-hour."""
    __tablename__ = "hourly_store_traffic_records"
    __table_args__ = (
        UniqueConstraint("store_id", "business_date", "hour_of_day", "source", "external_reference",
                         name="uq_hourly_traffic_external_reference"),
        CheckConstraint("customer_count >= 0", name="ck_hourly_traffic_count_nonnegative"),
        CheckConstraint("hour_of_day >= 0 AND hour_of_day <= 23", name="ck_hourly_traffic_hour_range"),
        CheckConstraint("source IN ('POS', 'ERP', 'MANUAL', 'IMPORT')", name="ck_hourly_traffic_source"),
        Index("ix_hourly_traffic_store_date_hour", "store_id", "business_date", "hour_of_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    business_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    hour_of_day: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    customer_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class StorePallet(Base):
    """Identity and current operational state of one physical pallet."""
    __tablename__ = "store_pallets"
    __table_args__ = (
        UniqueConstraint("store_id", "pallet_code", name="uq_store_pallet_store_code"),
        CheckConstraint("base_quantity >= 0", name="ck_store_pallet_quantity_nonnegative"),
        CheckConstraint("(status = 'EMPTY' AND base_quantity = 0) OR (status <> 'EMPTY' AND base_quantity > 0)", name="ck_store_pallet_status_quantity"),
        CheckConstraint("status IN ('READY', 'ON_DISPLAY', 'PARTIAL', 'RETURNED', 'REBUILDING', 'EMPTY', 'QUARANTINED')", name="ck_store_pallet_status"),
        CheckConstraint("location_type IN ('WAREHOUSE', 'PREPARATION', 'SALES_FLOOR', 'OTHER')", name="ck_store_pallet_location_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    packaging_level_id: Mapped[int] = mapped_column(ForeignKey("product_packaging_levels.id", ondelete="RESTRICT"), nullable=False, index=True)
    pallet_code: Mapped[str] = mapped_column(String(100), nullable=False)
    lot_code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    base_quantity: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="READY", nullable=False, index=True)
    location_type: Mapped[str] = mapped_column(String(16), default="WAREHOUSE", nullable=False)
    location_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class PalletRotationPolicy(Base):
    """Store/product-specific policy for evaluating pallet exchange."""
    __tablename__ = "pallet_rotation_policies"
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", name="uq_pallet_rotation_policy_store_product"),
        CheckConstraint("threshold_ratio > 0 AND threshold_ratio <= 1", name="ck_pallet_rotation_threshold_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    threshold_ratio: Mapped[float] = mapped_column(Numeric(5, 4), default=0.5, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class PalletRotationEvent(Base):
    """Append-only audit event for the lifecycle of a physical pallet."""
    __tablename__ = "pallet_rotation_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('REGISTERED', 'STATUS_REVIEWED', 'LOCATION_RECORDED', 'QUANTITY_RECORDED', 'LOT_REVIEWED', 'EXCEPTION_RECORDED')", name="ck_pallet_event_type"),
        CheckConstraint("quantity_before >= 0 AND quantity_after >= 0", name="ck_pallet_event_quantities_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    pallet_id: Mapped[int] = mapped_column(ForeignKey("store_pallets.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    from_location_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    from_location_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    to_location_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_location_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quantity_before: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    quantity_after: Mapped[float] = mapped_column(Numeric(14, 3), nullable=False)
    lot_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class InventoryExternalProductMapping(Base):
    """Explicit store/source-scoped mapping from a provider SKU to an internal product."""
    __tablename__ = "inventory_external_product_mappings"
    __table_args__ = (
        UniqueConstraint("store_id", "source", "external_product_id", name="uq_inventory_external_mapping_external_id"),
        UniqueConstraint("store_id", "source", "external_sku", name="uq_inventory_external_mapping_sku"),
        UniqueConstraint("store_id", "source", "product_id", name="uq_inventory_external_mapping_product"),
        CheckConstraint("source IN ('ERP', 'WMS')", name="ck_inventory_external_mapping_source"),
        Index("ix_inventory_external_mapping_product", "store_id", "product_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    external_product_id: Mapped[str] = mapped_column(String(120), nullable=False)
    external_sku: Mapped[str] = mapped_column(String(120), nullable=False)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    updated_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class InventoryExternalProductMappingEvent(Base):
    """Append-only audit trail for external product mapping administration."""
    __tablename__ = "inventory_external_product_mapping_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('CREATED', 'UPDATED', 'DEACTIVATED', 'REACTIVATED')",
                        name="ck_inventory_external_mapping_event_type"),
        Index("ix_inventory_external_mapping_events_mapping_created", "mapping_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    mapping_id: Mapped[int] = mapped_column(ForeignKey("inventory_external_product_mappings.id", ondelete="RESTRICT"), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(12), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after_state: Mapped[dict] = mapped_column(JSON, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class InventorySnapshot(Base):
    """Immutable observation of backroom stock from an authoritative source."""
    __tablename__ = "inventory_snapshots"
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", "source", "external_reference",
                         name="uq_inventory_snapshot_source_reference"),
        CheckConstraint("on_hand_quantity >= 0", name="ck_inventory_on_hand_nonnegative"),
        CheckConstraint("reserved_quantity >= 0", name="ck_inventory_reserved_nonnegative"),
        CheckConstraint("reserved_quantity <= on_hand_quantity", name="ck_inventory_reserved_lte_on_hand"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    on_hand_quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    reserved_quantity: Mapped[float] = mapped_column(Numeric(12, 3), default=0, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    @property
    def available_quantity(self) -> float:
        return float(self.on_hand_quantity - self.reserved_quantity)


class InventoryFreshnessPolicy(Base):
    """Maximum accepted age for inventory evidence, scoped to one store and source."""
    __tablename__ = "inventory_freshness_policies"
    __table_args__ = (
        UniqueConstraint("store_id", "source", name="uq_inventory_freshness_store_source"),
        CheckConstraint("source IN ('ERP', 'WMS', 'POS', 'MANUAL', 'IMPORT')", name="ck_inventory_freshness_source"),
        CheckConstraint("max_age_minutes >= 1 AND max_age_minutes <= 10080", name="ck_inventory_freshness_max_age"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    max_age_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=240)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False)


class InventoryReconciliation(Base):
    """Immutable evidence snapshot with a separately governed human review state."""
    __tablename__ = "inventory_reconciliations"
    __table_args__ = (
        CheckConstraint("review_status IN ('PENDING', 'APPROVED', 'REJECTED', 'NEEDS_INVESTIGATION')", name="ck_inventory_reconciliation_review_status"),
        CheckConstraint("display_quantity IS NULL OR display_quantity >= 0", name="ck_inventory_reconciliation_display_quantity"),
        CheckConstraint("wms_available_quantity IS NULL OR wms_available_quantity >= 0", name="ck_inventory_reconciliation_wms_quantity"),
        CheckConstraint("erp_available_quantity IS NULL OR erp_available_quantity >= 0", name="ck_inventory_reconciliation_erp_quantity"),
        Index("ix_inventory_reconciliation_store_status_created", "store_id", "review_status", "created_at"),
        Index("ix_inventory_reconciliation_product_created", "store_id", "product_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True)
    shelf_id: Mapped[int] = mapped_column(ForeignKey("shelves.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    observation_id: Mapped[int | None] = mapped_column(ForeignKey("observations.id", ondelete="SET NULL"), nullable=True)
    backroom_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_snapshots.id", ondelete="SET NULL"), nullable=True)
    erp_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_snapshots.id", ondelete="SET NULL"), nullable=True)
    wms_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_snapshots.id", ondelete="SET NULL"), nullable=True)
    display_target_quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    display_quantity: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    wms_available_quantity: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    erp_available_quantity: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    display_delta: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    display_vs_wms_delta: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    display_vs_erp_delta: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    wms_erp_delta: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    comparison_status: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False)
    review_status: Mapped[str] = mapped_column(String(24), default="PENDING", nullable=False, index=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class InventoryReconciliationEvent(Base):
    """Append-only audit trail for reconciliation creation and human decisions."""
    __tablename__ = "inventory_reconciliation_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('CREATED', 'APPROVED', 'REJECTED', 'NEEDS_INVESTIGATION')", name="ck_inventory_reconciliation_event_type"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    reconciliation_id: Mapped[int] = mapped_column(ForeignKey("inventory_reconciliations.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class InventoryMovement(Base):
    """Immutable, approved transfer from backroom stock to shelf."""
    __tablename__ = "inventory_movements"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_inventory_movement_task"),
        UniqueConstraint("result_snapshot_id", name="uq_inventory_movement_result_snapshot"),
        CheckConstraint("movement_type = 'BACKROOM_TO_SHELF'", name="ck_inventory_movement_type"),
        CheckConstraint("quantity > 0", name="ck_inventory_movement_quantity_positive"),
        CheckConstraint("source_snapshot_id <> result_snapshot_id", name="ck_inventory_movement_distinct_snapshots"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("replenishment_tasks.id", ondelete="RESTRICT"), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True)
    movement_type: Mapped[str] = mapped_column(String(30), nullable=False, default="BACKROOM_TO_SHELF")
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    source_snapshot_id: Mapped[int] = mapped_column(ForeignKey("inventory_snapshots.id", ondelete="RESTRICT"), nullable=False, index=True)
    result_snapshot_id: Mapped[int] = mapped_column(ForeignKey("inventory_snapshots.id", ondelete="RESTRICT"), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class ReplenishmentTask(Base):
    """Operational task for replenishing one product on one shelf."""
    __tablename__ = "replenishment_tasks"
    __table_args__ = (
        CheckConstraint("priority IN ('LOW', 'NORMAL', 'HIGH', 'URGENT')", name="ck_task_priority"),
        CheckConstraint("status IN ('PENDING', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED', 'CANCELLED')", name="ck_task_status"),
        CheckConstraint("requested_quantity IS NULL OR requested_quantity > 0", name="ck_task_quantity_positive"),
        CheckConstraint("estimated_duration_minutes BETWEEN 1 AND 480", name="ck_task_estimated_duration_positive"),
        Index(
            "uq_active_task_store_shelf_product",
            "store_id", "shelf_id", "product_id",
            unique=True,
            postgresql_where=text("status IN ('PENDING', 'ASSIGNED', 'IN_PROGRESS')"),
            sqlite_where=text("status IN ('PENDING', 'ASSIGNED', 'IN_PROGRESS')"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    shelf_id: Mapped[int] = mapped_column(ForeignKey("shelves.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    priority: Mapped[str] = mapped_column(String(12), default="NORMAL", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", index=True, nullable=False)
    assigned_to: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    requested_quantity: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    estimated_duration_minutes: Mapped[int] = mapped_column(Integer, default=15, nullable=False)
    required_skill_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actual_quantity: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReplenishmentTaskEvent(Base):
    """Append-only audit record for task approvals and lifecycle transitions."""
    __tablename__ = "replenishment_task_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('CREATED', 'APPROVED', 'STATUS_CHANGED', 'INVENTORY_RECONCILED')", name="ck_task_event_type"),
        CheckConstraint("actual_quantity IS NULL OR actual_quantity > 0", name="ck_task_event_actual_quantity_positive"),
        Index("ix_task_events_task_created", "task_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("replenishment_tasks.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    actual_quantity: Mapped[float | None] = mapped_column(Numeric(12, 3), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class User(Base):
    """Application account with a role scoped to the platform."""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('ADMIN', 'SUPERVISOR', 'EMPLOYEE')", name="ck_user_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True, nullable=False)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="EMPLOYEE", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CaptureSession(Base):
    """Operational capture batch used to keep related frames in one dataset split."""
    __tablename__ = "capture_sessions"
    __table_args__ = (
        CheckConstraint("source_type IN ('fixed_camera', 'robot', 'mobile')", name="ck_capture_session_source"),
        CheckConstraint("capture_mode IN ('single', 'burst', 'video_sample')", name="ck_capture_session_mode"),
        CheckConstraint("ended_at IS NULL OR ended_at >= started_at", name="ck_capture_session_time_range"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True, nullable=False)
    shelf_id: Mapped[int] = mapped_column(ForeignKey("shelves.id", ondelete="CASCADE"), index=True, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_device_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    capture_mode: Mapped[str] = mapped_column(String(20), default="single", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShelfImage(Base):
    """Stored shelf capture awaiting computer-vision analysis."""
    __tablename__ = "shelf_images"
    __table_args__ = (
        CheckConstraint(
            "retention_status IN ('ACTIVE', 'RESTRICTED', 'PENDING_PURGE', 'PURGED')",
            name="ck_shelf_images_retention_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shelf_id: Mapped[int] = mapped_column(ForeignKey("shelves.id", ondelete="CASCADE"), index=True)
    capture_session_id: Mapped[int | None] = mapped_column(ForeignKey("capture_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(600), unique=True, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(40), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    analysis_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False, index=True)
    analysis_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    analysis_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    retention_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False, index=True)
    retention_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    retention_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    purge_not_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_policy_version: Mapped[str | None] = mapped_column(String(40), nullable=True)


class ShelfImageArtifactReference(Base):
    """Append-only declaration of an external artifact derived from a shelf image."""
    __tablename__ = "shelf_image_artifact_references"
    __table_args__ = (
        CheckConstraint(
            "artifact_type IN ('DATASET_COPY', 'DATASET_RELEASE', 'CROP', 'REPORT', 'BACKUP', 'CACHE', 'OBJECT_REPLICA', 'OTHER')",
            name="ck_shelf_image_artifact_type",
        ),
        CheckConstraint(
            "sha256 IS NULL OR length(sha256) = 64",
            name="ck_shelf_image_artifact_sha256_length",
        ),
        UniqueConstraint(
            "shelf_image_id", "artifact_type", "external_system", "external_reference",
            name="uq_shelf_image_artifact_reference",
        ),
        Index(
            "uq_shelf_image_artifact_reference_lineage",
            "id", "shelf_image_id", "store_id",
            unique=True,
        ),
        ForeignKeyConstraint(
            ["parent_reference_id", "shelf_image_id", "store_id"],
            [
                "shelf_image_artifact_references.id",
                "shelf_image_artifact_references.shelf_image_id",
                "shelf_image_artifact_references.store_id",
            ],
            name="fk_artifact_reference_parent_lineage",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "parent_reference_id IS NULL OR parent_reference_id <> id",
            name="ck_artifact_reference_parent_not_self",
        ),
        Index("ix_artifact_reference_parent_reference_id", "parent_reference_id"),
        Index("ix_shelf_image_artifacts_store_image", "store_id", "shelf_image_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    shelf_image_id: Mapped[int] = mapped_column(ForeignKey("shelf_images.id", ondelete="RESTRICT"), nullable=False, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(24), nullable=False)
    external_system: Mapped[str] = mapped_column(String(120), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(500), nullable=False)
    release_id: Mapped[str | None] = mapped_column(String(160), nullable=True, index=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    declared_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShelfImageArtifactInventorySnapshot(Base):
    """Append-only, source-signed inventory snapshot for one image and external system."""
    __tablename__ = "shelf_image_artifact_inventory_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "store_id", "external_system", "snapshot_id",
            name="uq_shelf_image_artifact_inventory_snapshot_source_id",
        ),
        CheckConstraint("artifact_count >= 0", name="ck_artifact_inventory_count_nonnegative"),
        CheckConstraint("present_count >= 0 AND absent_count >= 0", name="ck_artifact_inventory_state_counts_nonnegative"),
        CheckConstraint("present_count + absent_count = artifact_count", name="ck_artifact_inventory_state_counts_total"),
        CheckConstraint("length(manifest_sha256) = 64", name="ck_artifact_inventory_manifest_sha256_length"),
        CheckConstraint("length(source_signature) = 64", name="ck_artifact_inventory_signature_length"),
        Index("ix_artifact_inventory_snapshot_image_source_time", "shelf_image_id", "external_system", "generated_at"),
        Index("ix_artifact_inventory_snapshot_store_source_time", "store_id", "external_system", "generated_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shelf_image_id: Mapped[int] = mapped_column(ForeignKey("shelf_images.id", ondelete="RESTRICT"), nullable=False, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True)
    external_system: Mapped[str] = mapped_column(String(120), nullable=False)
    snapshot_id: Mapped[str] = mapped_column(String(160), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    inventory_complete: Mapped[bool] = mapped_column(Boolean, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_signature: Mapped[str] = mapped_column(String(64), nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), default="legacy", nullable=False)
    inventory_manifest: Mapped[list] = mapped_column(JSON, nullable=False)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False)
    present_count: Mapped[int] = mapped_column(Integer, nullable=False)
    absent_count: Mapped[int] = mapped_column(Integer, nullable=False)
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShelfImageArtifactDispositionEvent(Base):
    """Append-only two-person approval and evidence trail for external artifact disposition."""
    __tablename__ = "shelf_image_artifact_disposition_events"
    __table_args__ = (
        UniqueConstraint(
            "artifact_reference_id", "sequence_number",
            name="uq_shelf_image_artifact_disposition_sequence",
        ),
        ForeignKeyConstraint(
            ["artifact_reference_id", "shelf_image_id", "store_id"],
            [
                "shelf_image_artifact_references.id",
                "shelf_image_artifact_references.shelf_image_id",
                "shelf_image_artifact_references.store_id",
            ],
            name="fk_shelf_image_artifact_disposition_reference_lineage",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "sequence_number > 0",
            name="ck_shelf_image_artifact_disposition_sequence_positive",
        ),
        CheckConstraint(
            "event_type IN ('PROPOSED', 'APPROVED', 'REJECTED', 'DISPOSAL_ATTESTED')",
            name="ck_shelf_image_artifact_disposition_event_type",
        ),
        CheckConstraint(
            "evidence_sha256 IS NULL OR length(evidence_sha256) = 64",
            name="ck_shelf_image_artifact_disposition_evidence_sha256_length",
        ),
        Index(
            "ix_shelf_image_artifact_disposition_artifact_created",
            "artifact_reference_id", "created_at",
        ),
        Index(
            "ix_shelf_image_artifact_disposition_store_image",
            "store_id", "shelf_image_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    artifact_reference_id: Mapped[int] = mapped_column(
        ForeignKey("shelf_image_artifact_references.id", ondelete="RESTRICT"),
        nullable=False,
    )
    shelf_image_id: Mapped[int] = mapped_column(
        ForeignKey("shelf_images.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    evidence_reference: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False,
    )


class ShelfImageRetentionEvent(Base):
    """Append-only audit trail for shelf-image retention state changes."""
    __tablename__ = "shelf_image_retention_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('RESTRICTED', 'RESTORED', 'LEGAL_HOLD_APPLIED', 'LEGAL_HOLD_RELEASED', 'PURGE_SCHEDULED', 'PURGE_CANCELLED')", name="ck_shelf_image_retention_event_type"),
        Index("ix_shelf_image_retention_events_image_created", "shelf_image_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shelf_image_id: Mapped[int] = mapped_column(ForeignKey("shelf_images.id", ondelete="RESTRICT"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(20), nullable=False)
    from_status: Mapped[str] = mapped_column(String(20), nullable=False)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShelfImageDetection(Base):
    """A single object detection produced by a computer-vision model."""
    __tablename__ = "shelf_image_detections"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_detection_confidence_range"),
        CheckConstraint("x_min >= 0 AND x_min <= 1 AND y_min >= 0 AND y_min <= 1", name="ck_detection_bbox_min_range"),
        CheckConstraint("x_max >= 0 AND x_max <= 1 AND y_max >= 0 AND y_max <= 1", name="ck_detection_bbox_max_range"),
        CheckConstraint("x_min < x_max AND y_min < y_max", name="ck_detection_bbox_order"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shelf_image_id: Mapped[int] = mapped_column(ForeignKey("shelf_images.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    label: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    x_min: Mapped[float] = mapped_column(Float, nullable=False)
    y_min: Mapped[float] = mapped_column(Float, nullable=False)
    x_max: Mapped[float] = mapped_column(Float, nullable=False)
    y_max: Mapped[float] = mapped_column(Float, nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    sku_match_status: Mapped[str] = mapped_column(String(12), default="UNKNOWN", nullable=False)
    sku_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    sku_match_margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class DetectionSkuReview(Base):
    """Append-only human decision about the SKU assigned to a detection."""
    __tablename__ = "detection_sku_reviews"
    __table_args__ = (
        CheckConstraint("decision IN ('CONFIRMED', 'CORRECTED', 'REJECTED')", name="ck_detection_sku_review_decision"),
        CheckConstraint("(decision = 'REJECTED' AND selected_product_id IS NULL) OR (decision IN ('CONFIRMED', 'CORRECTED') AND selected_product_id IS NOT NULL)", name="ck_detection_sku_review_selected_product"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    detection_id: Mapped[int] = mapped_column(ForeignKey("shelf_image_detections.id", ondelete="CASCADE"), index=True, nullable=False)
    previous_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    selected_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"), nullable=True, index=True)
    decision: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    reviewer_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)



class ShelfImageOCRRun(Base):
    """Append-only record of one OCR inference pass over a shelf image."""
    __tablename__ = "shelf_image_ocr_runs"
    __table_args__ = (
        CheckConstraint("status IN ('COMPLETED', 'FAILED')", name="ck_shelf_image_ocr_run_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    shelf_image_id: Mapped[int] = mapped_column(ForeignKey("shelf_images.id", ondelete="CASCADE"), index=True, nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="COMPLETED", nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShelfImageOCREvidence(Base):
    """Immutable OCR text region and optional association to one product detection."""
    __tablename__ = "shelf_image_ocr_evidence"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_shelf_ocr_confidence_range"),
        CheckConstraint("x_min >= 0 AND x_min <= 1 AND y_min >= 0 AND y_min <= 1", name="ck_shelf_ocr_bbox_min_range"),
        CheckConstraint("x_max >= 0 AND x_max <= 1 AND y_max >= 0 AND y_max <= 1", name="ck_shelf_ocr_bbox_max_range"),
        CheckConstraint("x_min < x_max AND y_min < y_max", name="ck_shelf_ocr_bbox_order"),
        CheckConstraint("association_status IN ('ASSIGNED', 'UNASSIGNED')", name="ck_shelf_ocr_association_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("shelf_image_ocr_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    detection_id: Mapped[int | None] = mapped_column(ForeignKey("shelf_image_detections.id", ondelete="SET NULL"), index=True, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(String(1000), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    x_min: Mapped[float] = mapped_column(Float, nullable=False)
    y_min: Mapped[float] = mapped_column(Float, nullable=False)
    x_max: Mapped[float] = mapped_column(Float, nullable=False)
    y_max: Mapped[float] = mapped_column(Float, nullable=False)
    association_status: Mapped[str] = mapped_column(String(12), default="UNASSIGNED", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShelfImageOCRMatch(Base):
    """Append-only catalogue matching result for one detected product and OCR run."""
    __tablename__ = "shelf_image_ocr_matches"
    __table_args__ = (
        UniqueConstraint("run_id", "detection_id", name="uq_ocr_match_run_detection"),
        CheckConstraint("status IN ('SUGGESTED', 'AMBIGUOUS', 'UNKNOWN')", name="ck_ocr_match_status"),
        CheckConstraint("top_score IS NULL OR (top_score >= 0 AND top_score <= 1)", name="ck_ocr_match_score"),
        CheckConstraint("ocr_confidence >= 0 AND ocr_confidence <= 1", name="ck_ocr_match_confidence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("shelf_image_ocr_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    detection_id: Mapped[int] = mapped_column(ForeignKey("shelf_image_detections.id", ondelete="CASCADE"), index=True, nullable=False)
    suggested_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    observed_text: Mapped[str] = mapped_column(Text, nullable=False)
    ocr_confidence: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, index=True)
    top_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    margin: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidates: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShelfImageFusedEvidence(Base):
    """Immutable visual/OCR fusion suggestion for one detection and OCR run."""
    __tablename__ = "shelf_image_fused_evidence"
    __table_args__ = (
        UniqueConstraint("ocr_run_id", "detection_id", name="uq_fused_evidence_run_detection"),
        CheckConstraint("status IN ('CONSENSUS', 'VISUAL_ONLY', 'TEXT_ONLY', 'CONFLICT', 'AMBIGUOUS', 'UNKNOWN')", name="ck_fused_evidence_status"),
        CheckConstraint("ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)", name="ck_fused_evidence_ocr_confidence"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ocr_run_id: Mapped[int] = mapped_column(ForeignKey("shelf_image_ocr_runs.id", ondelete="CASCADE"), index=True, nullable=False)
    detection_id: Mapped[int] = mapped_column(ForeignKey("shelf_image_detections.id", ondelete="CASCADE"), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    suggested_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    visual_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    text_product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"), nullable=True)
    visual_status: Mapped[str] = mapped_column(String(12), nullable=False)
    text_status: Mapped[str] = mapped_column(String(12), nullable=False)
    visual_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    text_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    visual_model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ocr_provider: Mapped[str] = mapped_column(String(80), nullable=False)
    ocr_model_version: Mapped[str] = mapped_column(String(120), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DailySalesRecord(Base):
    """Immutable daily POS/ERP sales aggregate for one store and product."""
    __tablename__ = "daily_sales_records"
    __table_args__ = (
        UniqueConstraint("store_id", "product_id", "sales_date", "source", "external_reference",
                         name="uq_daily_sales_external_reference"),
        CheckConstraint("quantity >= 0", name="ck_daily_sales_quantity_nonnegative"),
        CheckConstraint("source IN ('POS', 'ERP', 'MANUAL', 'IMPORT')", name="ck_daily_sales_source"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    sales_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    external_reference: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DatasetExecutionJob(Base):
    """Durable approval-bound dataset execution job with a fenced worker lease."""
    __tablename__ = "dataset_execution_jobs"
    __table_args__ = (
        CheckConstraint("status IN ('QUEUED', 'LEASED', 'SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')", name="ck_dataset_execution_job_status"),
        CheckConstraint("mode IN ('training', 'inference')", name="ck_dataset_execution_job_mode"),
        CheckConstraint("length(release_fingerprint) = 64", name="ck_dataset_execution_job_release_digest"),
        CheckConstraint("length(approval_record_sha256) = 64", name="ck_dataset_execution_job_record_digest"),
        CheckConstraint("length(approval_report_sha256) = 64", name="ck_dataset_execution_job_report_digest"),
        CheckConstraint("length(request_sha256) = 64", name="ck_dataset_execution_job_request_digest"),
        CheckConstraint("fencing_token >= 0", name="ck_dataset_execution_job_fencing_nonnegative"),
        CheckConstraint("attempt_count >= 0", name="ck_dataset_execution_job_attempts_nonnegative"),
        CheckConstraint("(status = 'LEASED' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'LEASED' AND lease_owner IS NULL AND lease_expires_at IS NULL)", name="ck_dataset_execution_job_lease_state"),
        CheckConstraint("output_sha256 IS NULL OR length(output_sha256) = 64", name="ck_dataset_execution_job_output_digest"),
        CheckConstraint("status <> 'SUCCEEDED' OR (output_sha256 IS NOT NULL AND staged_output_reference IS NOT NULL)", name="ck_dataset_execution_job_success_output"),
        CheckConstraint("(status IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') AND finished_at IS NOT NULL) OR (status NOT IN ('SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED') AND finished_at IS NULL)", name="ck_dataset_execution_job_finished_state"),
        CheckConstraint("status <> 'LEASED' OR (fencing_token > 0 AND attempt_count > 0)", name="ck_dataset_execution_job_active_fencing"),
        UniqueConstraint("idempotency_key", name="uq_dataset_execution_job_idempotency"),
        Index("ix_dataset_execution_jobs_claim", "status", "lease_expires_at", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    release_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_record_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    approval_report_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="QUEUED", nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    staged_output_reference: Mapped[str | None] = mapped_column(String(600), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatasetExecutionJobSource(Base):
    """Immutable internal image dependency captured by a dataset execution job."""
    __tablename__ = "dataset_execution_job_sources"
    __table_args__ = (
        UniqueConstraint("job_id", "shelf_image_id", name="uq_dataset_execution_job_source"),
        CheckConstraint("length(source_image_sha256) = 64", name="ck_dataset_execution_source_digest"),
        Index("ix_dataset_execution_job_sources_image", "shelf_image_id", "job_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("dataset_execution_jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    shelf_image_id: Mapped[int] = mapped_column(ForeignKey("shelf_images.id", ondelete="RESTRICT"), nullable=False, index=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False, index=True)
    source_image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DatasetExecutionJobEvent(Base):
    """Append-only audit event for durable dataset job lease and lifecycle changes."""
    __tablename__ = "dataset_execution_job_events"
    __table_args__ = (
        UniqueConstraint("job_id", "sequence_number", name="uq_dataset_execution_job_event_sequence"),
        CheckConstraint("event_type IN ('QUEUED', 'CLAIMED', 'HEARTBEAT', 'SUCCEEDED', 'FAILED', 'REVOKED', 'CANCELLED')", name="ck_dataset_execution_job_event_type"),
        CheckConstraint("fencing_token >= 0", name="ck_dataset_execution_job_event_fencing_nonnegative"),
        Index("ix_dataset_execution_job_events_job_sequence", "job_id", "sequence_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("dataset_execution_jobs.id", ondelete="RESTRICT"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)



class EdgeDevice(Base):
    """Store-bound physical edge device identity, independent from dataset workers."""
    __tablename__ = "edge_devices"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_edge_device_status"),
        CheckConstraint("device_type IN ('fixed_camera', 'robot', 'mobile', 'gateway')", name="ck_edge_device_type"),
        Index("ix_edge_devices_store_status", "store_id", "status"),
        CheckConstraint("last_network_status IS NULL OR last_network_status IN ('ONLINE', 'DEGRADED', 'OFFLINE')", name="ck_edge_device_network_status"),
        CheckConstraint("battery_pct IS NULL OR (battery_pct >= 0 AND battery_pct <= 100)", name="ck_edge_device_battery_pct"),
        CheckConstraint("storage_free_bytes IS NULL OR storage_free_bytes >= 0", name="ck_edge_device_storage_free_bytes"),
    )

    device_id: Mapped[str] = mapped_column(String(120), primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    device_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_network_status: Mapped[str | None] = mapped_column(String(12), nullable=True)
    firmware_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    battery_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_free_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class EdgeDeviceCredential(Base):
    """Individually revocable, hashed credential for one registered edge device."""
    __tablename__ = "edge_device_credentials"
    __table_args__ = (
        UniqueConstraint("credential_id", name="uq_edge_device_credential_public_id"),
        CheckConstraint("length(secret_sha256) = 64", name="ck_edge_device_credential_digest"),
        CheckConstraint("expires_at > created_at", name="ck_edge_device_credential_expiry"),
        Index("ix_edge_device_credentials_device_expiry", "device_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_id: Mapped[str] = mapped_column(String(32), nullable=False)
    device_id: Mapped[str] = mapped_column(ForeignKey("edge_devices.device_id", ondelete="RESTRICT"), nullable=False, index=True)
    secret_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_credential_id: Mapped[str | None] = mapped_column(String(32), nullable=True)


class EdgeDeviceAuditEvent(Base):
    """Append-only audit trail for edge device and credential lifecycle operations."""
    __tablename__ = "edge_device_audit_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('DEVICE_REGISTERED', 'DEVICE_DISABLED', 'CREDENTIAL_ISSUED', 'CREDENTIAL_ROTATED', 'CREDENTIAL_REVOKED')",
            name="ck_edge_device_audit_event_type",
        ),
        Index("ix_edge_device_audit_events_device_created", "device_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("edge_devices.device_id", ondelete="RESTRICT"), nullable=False)
    credential_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EdgeDeviceRequestNonce(Base):
    """Short-lived anti-replay nonce scoped to an edge-device credential."""
    __tablename__ = "edge_device_request_nonces"
    __table_args__ = (
        UniqueConstraint("credential_id", "nonce_sha256", name="uq_edge_device_nonce_credential_digest"),
        CheckConstraint("length(nonce_sha256) = 64", name="ck_edge_device_nonce_digest"),
        Index("ix_edge_device_request_nonces_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("edge_device_credentials.credential_id", ondelete="RESTRICT"), nullable=False)
    nonce_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_timestamp: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EdgeDeviceEventCursor(Base):
    """Monotonic accepted-event cursor for each physical device."""
    __tablename__ = "edge_device_event_cursors"
    __table_args__ = (CheckConstraint("last_sequence >= 0", name="ck_edge_device_cursor_nonnegative"),)

    device_id: Mapped[str] = mapped_column(ForeignKey("edge_devices.device_id", ondelete="RESTRICT"), primary_key=True)
    last_sequence: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EdgeDeviceEventInbox(Base):
    """Durable, immutable inbox of authenticated edge events awaiting processing."""
    __tablename__ = "edge_device_event_inbox"
    __table_args__ = (
        UniqueConstraint("device_id", "event_id", name="uq_edge_device_inbox_event"),
        UniqueConstraint("device_id", "sequence_number", name="uq_edge_device_inbox_sequence"),
        CheckConstraint("sequence_number > 0", name="ck_edge_device_inbox_sequence_positive"),
        CheckConstraint("length(fingerprint_sha256) = 64", name="ck_edge_device_inbox_fingerprint"),
        Index("ix_edge_device_inbox_store_received", "store_id", "received_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("edge_devices.device_id", ondelete="RESTRICT"), nullable=False)
    event_id: Mapped[str] = mapped_column(String(36), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    shelf_id: Mapped[int | None] = mapped_column(ForeignKey("shelves.id", ondelete="RESTRICT"), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    fingerprint_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EdgeDeviceEventProcessing(Base):
    """Mutable processing control row; the authenticated event inbox remains immutable."""
    __tablename__ = "edge_device_event_processing"
    __table_args__ = (
        UniqueConstraint("inbox_id", name="uq_edge_event_processing_inbox"),
        CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'PROCESSED', 'RETRY', 'DEAD_LETTER')",
            name="ck_edge_event_processing_status",
        ),
        CheckConstraint("attempt_count >= 0 AND max_attempts > 0", name="ck_edge_event_processing_attempts"),
        CheckConstraint("fencing_token >= 0", name="ck_edge_event_processing_fencing"),
        CheckConstraint(
            "(status = 'PROCESSING' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) "
            "OR (status <> 'PROCESSING' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_edge_event_processing_lease_state",
        ),
        CheckConstraint(
            "(status IN ('PROCESSED', 'DEAD_LETTER') AND finished_at IS NOT NULL) "
            "OR (status NOT IN ('PROCESSED', 'DEAD_LETTER') AND finished_at IS NULL)",
            name="ck_edge_event_processing_finished_state",
        ),
        Index("ix_edge_event_processing_claim", "status", "available_at", "lease_expires_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inbox_id: Mapped[int] = mapped_column(
        ForeignKey("edge_device_event_inbox.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DatasetWorker(Base):
    """Registered non-human identity allowed to process dataset execution jobs."""
    __tablename__ = "dataset_workers"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'DISABLED')", name="ck_dataset_worker_status"),
        Index("ix_dataset_workers_status_created", "status", "created_at"),
    )

    worker_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DatasetWorkerCredential(Base):
    """Hashed, individually revocable credential for one dataset worker."""
    __tablename__ = "dataset_worker_credentials"
    __table_args__ = (
        UniqueConstraint("credential_id", name="uq_dataset_worker_credential_public_id"),
        CheckConstraint("length(secret_sha256) = 64", name="ck_dataset_worker_credential_digest"),
        CheckConstraint("expires_at > created_at", name="ck_dataset_worker_credential_expiry"),
        Index("ix_dataset_worker_credentials_worker_expiry", "worker_id", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_id: Mapped[str] = mapped_column(String(32), nullable=False)
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_workers.worker_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    secret_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_credential_id: Mapped[str | None] = mapped_column(
        ForeignKey("dataset_worker_credentials.credential_id", ondelete="RESTRICT"), nullable=True
    )
    worker: Mapped["DatasetWorker"] = relationship()


class DatasetWorkerEvent(Base):
    """Append-only security audit event for worker and credential lifecycle changes."""
    __tablename__ = "dataset_worker_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('WORKER_REGISTERED', 'CREDENTIAL_ISSUED', 'CREDENTIAL_ROTATED', "
            "'CREDENTIAL_REVOKED', 'WORKER_DISABLED')",
            name="ck_dataset_worker_event_type",
        ),
        Index("ix_dataset_worker_events_worker_created", "worker_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_workers.worker_id", ondelete="RESTRICT"), nullable=False, index=True
    )
    credential_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DatasetWorkerRequestNonce(Base):
    """Short-lived nonce used to reject replayed signed worker requests."""
    __tablename__ = "dataset_worker_request_nonces"
    __table_args__ = (
        UniqueConstraint("credential_id", "nonce_sha256", name="uq_dataset_worker_request_nonce_credential_digest"),
        CheckConstraint("length(nonce_sha256) = 64", name="ck_dataset_worker_request_nonce_digest"),
        Index("ix_dataset_worker_request_nonces_expires", "expires_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_worker_credentials.credential_id", ondelete="RESTRICT"),
        nullable=False,
    )
    nonce_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    request_timestamp: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DatasetExecutionJobArtifactRead(Base):
    """Append-only audit record for a worker reading one approved job source."""
    __tablename__ = "dataset_execution_job_artifact_reads"
    __table_args__ = (
        CheckConstraint("fencing_token > 0", name="ck_dataset_job_artifact_read_fencing_positive"),
        CheckConstraint("length(source_image_sha256) = 64", name="ck_dataset_job_artifact_read_digest"),
        CheckConstraint("bytes_read > 0", name="ck_dataset_job_artifact_read_bytes_positive"),
        Index("ix_dataset_job_artifact_reads_job_created", "job_id", "created_at", "id"),
        Index("ix_dataset_job_artifact_reads_image_created", "shelf_image_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_execution_jobs.id", ondelete="RESTRICT"), nullable=False
    )
    shelf_image_id: Mapped[int] = mapped_column(
        ForeignKey("shelf_images.id", ondelete="RESTRICT"), nullable=False
    )
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_workers.worker_id", ondelete="RESTRICT"), nullable=False
    )
    credential_id: Mapped[str] = mapped_column(
        ForeignKey("dataset_worker_credentials.credential_id", ondelete="RESTRICT"), nullable=False
    )
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    source_image_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bytes_read: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DatasetExecutionJobOutputPublication(Base):
    """Append-only record of a verified, lease-fenced dataset output promotion."""
    __tablename__ = "dataset_execution_job_output_publications"
    __table_args__ = (
        CheckConstraint("fencing_token > 0", name="ck_dataset_job_output_publication_fencing_positive"),
        CheckConstraint("length(output_sha256) = 64", name="ck_dataset_job_output_publication_digest"),
        CheckConstraint("bytes_published > 0", name="ck_dataset_job_output_publication_bytes_positive"),
        CheckConstraint("published_output_reference LIKE 'published/%'", name="ck_dataset_job_output_publication_reference"),
        UniqueConstraint("job_id", name="uq_dataset_job_output_publication_job"),
        UniqueConstraint("published_output_reference", name="uq_dataset_job_output_publication_reference"),
        Index("ix_dataset_job_output_publications_worker_created", "worker_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("dataset_execution_jobs.id", ondelete="RESTRICT"), nullable=False)
    worker_id: Mapped[str] = mapped_column(ForeignKey("dataset_workers.worker_id", ondelete="RESTRICT"), nullable=False)
    credential_id: Mapped[str] = mapped_column(ForeignKey("dataset_worker_credentials.credential_id", ondelete="RESTRICT"), nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    output_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    staged_output_reference: Mapped[str] = mapped_column(String(600), nullable=False)
    published_output_reference: Mapped[str] = mapped_column(String(600), nullable=False)
    bytes_published: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DatasetExecutionJobOutputLineage(Base):
    """Immutable parent/derived publication edge; edges point parent -> child."""
    __tablename__ = "dataset_execution_job_output_lineage"
    __table_args__ = (
        CheckConstraint("parent_publication_id <> child_publication_id", name="ck_dataset_output_lineage_not_self"),
        UniqueConstraint("parent_publication_id", "child_publication_id", name="uq_dataset_output_lineage_edge"),
        Index("ix_dataset_output_lineage_child", "child_publication_id", "parent_publication_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_publication_id: Mapped[int] = mapped_column(ForeignKey("dataset_execution_job_output_publications.id", ondelete="RESTRICT"), nullable=False)
    child_publication_id: Mapped[int] = mapped_column(ForeignKey("dataset_execution_job_output_publications.id", ondelete="RESTRICT"), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DatasetExecutionJobOutputGovernanceEvent(Base):
    """Append-only restriction and legal-hold history for one published output."""
    __tablename__ = "dataset_execution_job_output_governance_events"
    __table_args__ = (
        UniqueConstraint("publication_id", "sequence_number", name="uq_dataset_output_governance_publication_sequence"),
        CheckConstraint("sequence_number > 0", name="ck_dataset_output_governance_sequence_positive"),
        CheckConstraint(
            "event_type IN ('RESTRICTION_APPLIED', 'RESTRICTION_RELEASED', 'LEGAL_HOLD_APPLIED', 'LEGAL_HOLD_RELEASED')",
            name="ck_dataset_output_governance_event_type",
        ),
        CheckConstraint("length(trim(reason)) > 0", name="ck_dataset_output_governance_reason_nonempty"),
        CheckConstraint(
            "(evidence_reference IS NULL AND evidence_sha256 IS NULL) OR "
            "(evidence_reference IS NOT NULL AND length(evidence_reference) > 0 "
            "AND evidence_sha256 IS NOT NULL AND length(evidence_sha256) = 64)",
            name="ck_dataset_output_governance_evidence_pair",
        ),
        Index("ix_dataset_output_governance_publication_sequence", "publication_id", "sequence_number"),
        Index("ix_dataset_output_governance_actor_created", "actor_user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("dataset_execution_job_output_publications.id", ondelete="RESTRICT"), nullable=False,
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(String(600), nullable=True)
    evidence_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class VisionModelReleaseState(Base):
    """Persistent high-water mark for one logical ONNX deployment slot."""

    __tablename__ = "vision_model_release_states"
    __table_args__ = (
        CheckConstraint("length(trim(deployment_id)) BETWEEN 1 AND 80", name="ck_vision_release_state_deployment"),
        CheckConstraint("length(trim(model_id)) BETWEEN 1 AND 80", name="ck_vision_release_state_model"),
        CheckConstraint("highest_release_version > 0", name="ck_vision_release_state_version"),
        CheckConstraint("length(manifest_sha256) = 64", name="ck_vision_release_state_manifest_digest"),
        CheckConstraint("length(detector_sha256) = 64", name="ck_vision_release_state_detector_digest"),
        CheckConstraint("embedding_sha256 IS NULL OR length(embedding_sha256) = 64", name="ck_vision_release_state_embedding_digest"),
    )

    deployment_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    model_id: Mapped[str] = mapped_column(String(80), nullable=False)
    highest_release_version: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detector_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class VisionModelReleaseEvent(Base):
    """Append-only audit trail for accepted and rejected signed model releases."""

    __tablename__ = "vision_model_release_events"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('ACCEPTED', 'REJECTED_ROLLBACK', 'REJECTED_VERSION_COLLISION', 'REJECTED_MODEL_ID_CHANGE')",
            name="ck_vision_release_event_decision",
        ),
        CheckConstraint("release_version > 0", name="ck_vision_release_event_version"),
        CheckConstraint("length(manifest_sha256) = 64", name="ck_vision_release_event_manifest_digest"),
        Index("ix_vision_model_release_events_deployment_created", "deployment_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    deployment_id: Mapped[str] = mapped_column(
        ForeignKey("vision_model_release_states.deployment_id", ondelete="RESTRICT"),
        nullable=False,
    )
    model_id: Mapped[str] = mapped_column(String(80), nullable=False)
    release_version: Mapped[int] = mapped_column(Integer, nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

class EmployeeShift(Base):
    """Persisted employee shift with an explicit working-capacity window."""
    __tablename__ = "employee_shifts"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_employee_shift_time_range"),
        CheckConstraint("break_minutes >= 0", name="ck_employee_shift_break_nonnegative"),
        CheckConstraint("status IN ('SCHEDULED', 'CANCELLED')", name="ck_employee_shift_status"),
        Index("ix_employee_shifts_store_start", "store_id", "starts_at"),
        Index("ix_employee_shifts_employee_start", "employee_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    break_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="SCHEDULED", nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EmployeeSkill(Base):
    """Employee competency, unique per employee and normalized skill code."""
    __tablename__ = "employee_skills"
    __table_args__ = (
        UniqueConstraint("employee_id", "skill_code", name="uq_employee_skill_code"),
        CheckConstraint("level BETWEEN 1 AND 5", name="ck_employee_skill_level"),
        Index("ix_employee_skills_store_code", "store_id", "skill_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    skill_code: Mapped[str] = mapped_column(String(60), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EmployeeAvailability(Base):
    """Explicit availability/unavailability interval for an employee."""
    __tablename__ = "employee_availability"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="ck_employee_availability_time_range"),
        CheckConstraint("status IN ('AVAILABLE', 'UNAVAILABLE')", name="ck_employee_availability_status"),
        Index("ix_employee_availability_employee_start", "employee_id", "starts_at"),
        Index("ix_employee_availability_store_start", "store_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)



class InventorySourceSync(Base):
    """Persistent lifecycle record for one ERP/WMS synchronization attempt."""
    __tablename__ = "inventory_source_syncs"
    __table_args__ = (
        CheckConstraint("source IN ('ERP', 'WMS')", name="ck_inventory_source_sync_source"),
        CheckConstraint("status IN ('STARTED', 'SUCCESS', 'PARTIAL', 'FAILED')", name="ck_inventory_source_sync_status"),
        CheckConstraint("received_records IS NULL OR received_records >= 0", name="ck_inventory_source_sync_received_nonnegative"),
        CheckConstraint("processed_records IS NULL OR processed_records >= 0", name="ck_inventory_source_sync_processed_nonnegative"),
        CheckConstraint("processed_records IS NULL OR received_records IS NULL OR processed_records <= received_records", name="ck_inventory_source_sync_processed_lte_received"),
        CheckConstraint("(status = 'STARTED' AND finished_at IS NULL) OR (status <> 'STARTED' AND finished_at IS NOT NULL)", name="ck_inventory_source_sync_completion_time"),
        Index("ix_inventory_source_sync_store_source_started", "store_id", "source", "started_at"),
        Index("ix_inventory_source_sync_store_status_started", "store_id", "status", "started_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    external_run_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="STARTED", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_records: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_records: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class InventorySourceSyncEvent(Base):
    """Append-only audit events for inventory source synchronization attempts."""
    __tablename__ = "inventory_source_sync_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('STARTED', 'COMPLETED')", name="ck_inventory_source_sync_event_type"),
        Index("ix_inventory_source_sync_events_sync_created", "sync_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    sync_id: Mapped[int] = mapped_column(ForeignKey("inventory_source_syncs.id", ondelete="RESTRICT"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(12), nullable=False)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class InventorySyncJob(Base):
    """Durable, idempotent request to synchronize one store/source."""
    __tablename__ = "inventory_sync_jobs"
    __table_args__ = (
        CheckConstraint("source IN ('ERP', 'WMS')", name="ck_inventory_sync_job_source"),
        CheckConstraint("status IN ('QUEUED', 'RUNNING', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')", name="ck_inventory_sync_job_status"),
        CheckConstraint("attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10 AND attempt_count <= max_attempts", name="ck_inventory_sync_job_attempts"),
        CheckConstraint("fencing_token >= 0", name="ck_inventory_sync_job_fencing"),
        CheckConstraint("(status = 'RUNNING' AND lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL) OR (status <> 'RUNNING' AND lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)", name="ck_inventory_sync_job_lease_state"),
        CheckConstraint("(status IN ('SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED') AND finished_at IS NOT NULL) OR (status IN ('QUEUED', 'RUNNING') AND finished_at IS NULL)", name="ck_inventory_sync_job_finished_state"),
        UniqueConstraint("store_id", "source", "idempotency_key", name="uq_inventory_sync_job_idempotency"),
        Index("ix_inventory_sync_jobs_claim", "status", "scheduled_at", "lease_expires_at", "created_at", "id"),
        Index("ix_inventory_sync_jobs_store_created", "store_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    requested_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="QUEUED", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(160), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_sync_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_source_syncs.id", ondelete="RESTRICT"), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class InventorySyncJobEvent(Base):
    """Append-only lifecycle audit for durable ERP/WMS sync jobs."""
    __tablename__ = "inventory_sync_job_events"
    __table_args__ = (
        CheckConstraint("event_type IN ('QUEUED', 'CLAIMED', 'LEASE_EXPIRED', 'HEARTBEAT', 'RETRY_SCHEDULED', 'SUCCEEDED', 'PARTIAL', 'FAILED', 'CANCELLED')", name="ck_inventory_sync_job_event_type"),
        UniqueConstraint("job_id", "sequence_number", name="uq_inventory_sync_job_event_sequence"),
        Index("ix_inventory_sync_job_events_job_created", "job_id", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("inventory_sync_jobs.id", ondelete="RESTRICT"), nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(24), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
