"""Integration coverage for inventory snapshot-to-sync run lineage."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.database import Base
from app.inventory_connectors.contracts import InventorySyncBatch, NormalizedInventoryRecord
from app.inventory_connectors.orchestrator import run_inventory_source_sync


class _WmsAdapter:
    source = "WMS"
    provider = "WMS-Lineage-Test"

    async def fetch_inventory(self, store_code, cursor=None):
        assert cursor is None
        return InventorySyncBatch(
            source="WMS",
            provider=self.provider,
            external_run_id="wms-lineage-run-1",
            records=(
                NormalizedInventoryRecord(
                    external_product_id="wms-product-1",
                    sku="LINEAGE-SKU-1",
                    on_hand_quantity=Decimal("25.000"),
                    reserved_quantity=Decimal("4.000"),
                    captured_at=datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc),
                    external_reference="wms-lineage-row-1",
                    location_code="BACKROOM-A",
                    availability_status="AVAILABLE",
                ),
            ),
        )


@pytest.mark.asyncio
async def test_ingested_inventory_snapshot_retains_originating_sync_run():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    try:
        with factory() as db:
            store = models.Store(code="WMS-LINEAGE-STORE", name="WMS lineage store")
            user = models.User(
                email="wms-lineage@example.test",
                full_name="WMS lineage actor",
                password_hash="test-only",
                role="ADMIN",
                store_id=None,
                is_active=True,
            )
            product = models.Product(
                sku="LINEAGE-SKU-1",
                name="Lineage product",
                unit="un",
                is_active=True,
            )
            db.add_all([store, user, product])
            db.flush()
            db.add(models.StoreExternalIntegration(
                store_id=store.id,
                external_system="WMS",
                provider="WMS-Lineage-Test",
                status="ACTIVE",
                created_by_user_id=user.id,
                updated_by_user_id=user.id,
            ))
            db.add(models.InventoryExternalProductMapping(
                store_id=store.id,
                source="WMS",
                external_product_id="wms-product-1",
                external_sku="LINEAGE-SKU-1",
                product_id=product.id,
                active=True,
                created_by_user_id=user.id,
                updated_by_user_id=user.id,
            ))
            db.commit()

            result = await run_inventory_source_sync(
                db,
                store_id=store.id,
                source="WMS",
                adapter=_WmsAdapter(),
                actor_user_id=user.id,
            )
            sync = db.get(models.InventorySourceSync, int(result["sync_id"]))
            snapshot = db.query(models.InventorySnapshot).filter_by(
                store_id=store.id,
                product_id=product.id,
                source="WMS",
                external_reference="wms-lineage-row-1",
            ).one()

            assert sync is not None and sync.status == "SUCCESS"
            assert snapshot.source_sync_id == sync.id
            assert snapshot.available_quantity == 21.0
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()
