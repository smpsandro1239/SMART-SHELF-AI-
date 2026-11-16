from datetime import date, datetime, timezone

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String, Text, Float, Integer, Boolean, Numeric, UniqueConstraint, CheckConstraint, ForeignKeyConstraint, Index, text
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
        Index("ix_shelf_image_artifacts_store_image", "store_id", "shelf_image_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
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
