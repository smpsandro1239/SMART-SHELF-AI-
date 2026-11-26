"""Authenticated, store-scoped administration and audit for ERP/WMS SKU mappings."""
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main as main_module
from app import models
from app.database import Base
from app.schemas import (
    InventoryExternalProductMappingCreate,
    InventoryExternalProductMappingUpdate,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _setup(db):
    store_a = models.Store(code="MAP-A", name="Store A")
    store_b = models.Store(code="MAP-B", name="Store B")
    db.add_all([store_a, store_b])
    db.flush()
    supervisor = models.User(
        email="mapping-supervisor@example.test", full_name="Supervisor",
        password_hash="test", role="SUPERVISOR", store_id=store_a.id, is_active=True,
    )
    employee = models.User(
        email="mapping-employee@example.test", full_name="Employee",
        password_hash="test", role="EMPLOYEE", store_id=store_a.id, is_active=True,
    )
    product_a = models.Product(sku="INTERNAL-A", name="Produto A", is_active=True)
    product_b = models.Product(sku="INTERNAL-B", name="Produto B", is_active=True)
    db.add_all([supervisor, employee, product_a, product_b])
    db.flush()
    db.add(models.StoreExternalIntegration(
        store_id=store_a.id, external_system="ERP", provider="ERP-Test",
        status="ACTIVE", created_by_user_id=supervisor.id, updated_by_user_id=supervisor.id,
    ))
    db.commit()
    return store_a, store_b, supervisor, employee, product_a, product_b


def _request(user):
    return SimpleNamespace(state=SimpleNamespace(user_id=user.id))


def test_mapping_create_update_and_audit_history(db_session):
    store, _, supervisor, _, product_a, product_b = _setup(db_session)
    request = _request(supervisor)
    created = main_module.create_inventory_external_product_mapping(
        store.id,
        InventoryExternalProductMappingCreate(
            source="ERP", external_product_id="vendor-100", external_sku="SKU-100",
            product_id=product_a.id, reason="Initial mapping approved",
        ),
        request,
        db_session,
    )
    assert created.product_id == product_a.id
    assert created.active is True

    updated = main_module.update_inventory_external_product_mapping(
        store.id, created.id,
        InventoryExternalProductMappingUpdate(
            product_id=product_b.id, reason="Vendor catalogue remapped",
        ),
        request, db_session,
    )
    assert updated["mapping"]["product_id"] == product_b.id
    assert updated["event_type"] == "UPDATED"

    deactivated = main_module.update_inventory_external_product_mapping(
        store.id, created.id,
        InventoryExternalProductMappingUpdate(active=False, reason="Supplier SKU retired"),
        request, db_session,
    )
    assert deactivated["event_type"] == "DEACTIVATED"

    history = main_module.list_inventory_external_product_mapping_events(
        store.id, created.id, request, db_session,
    )
    assert [event["event_type"] for event in history["items"]] == [
        "CREATED", "UPDATED", "DEACTIVATED",
    ]
    assert history["items"][1]["before_state"]["product_id"] == product_a.id
    assert history["items"][1]["after_state"]["product_id"] == product_b.id


def test_mapping_requires_active_source_integration_and_prevents_duplicate_sku(db_session):
    store, _, supervisor, _, product_a, product_b = _setup(db_session)
    request = _request(supervisor)
    payload = InventoryExternalProductMappingCreate(
        source="WMS", external_product_id="wms-1", external_sku="DUP-SKU",
        product_id=product_a.id, reason="Initial WMS mapping",
    )
    with pytest.raises(HTTPException) as missing:
        main_module.create_inventory_external_product_mapping(store.id, payload, request, db_session)
    assert missing.value.status_code == 409

    db_session.add(models.StoreExternalIntegration(
        store_id=store.id, external_system="WMS", provider="WMS-Test",
        status="ACTIVE", created_by_user_id=supervisor.id, updated_by_user_id=supervisor.id,
    ))
    db_session.commit()
    first = main_module.create_inventory_external_product_mapping(store.id, payload, request, db_session)
    duplicate = InventoryExternalProductMappingCreate(
        source="WMS", external_product_id="wms-2", external_sku="DUP-SKU",
        product_id=product_b.id, reason="Attempt duplicate SKU",
    )
    with pytest.raises(HTTPException) as conflict:
        main_module.create_inventory_external_product_mapping(store.id, duplicate, request, db_session)
    assert conflict.value.status_code == 409
    assert db_session.query(models.InventoryExternalProductMapping).count() == 1


def test_mapping_api_enforces_store_scope_and_role(db_session):
    store_a, store_b, supervisor, employee, product_a, _ = _setup(db_session)
    payload = InventoryExternalProductMappingCreate(
        source="ERP", external_product_id="vendor-200", external_sku="SKU-200",
        product_id=product_a.id, reason="Scoped mapping",
    )
    with pytest.raises(HTTPException) as foreign:
        main_module.create_inventory_external_product_mapping(
            store_b.id, payload, _request(supervisor), db_session,
        )
    assert foreign.value.status_code == 403

    with pytest.raises(HTTPException) as forbidden:
        main_module.create_inventory_external_product_mapping(
            store_a.id, payload, _request(employee), db_session,
        )
    assert forbidden.value.status_code == 403


def test_mapping_event_history_hides_foreign_mapping_and_preserves_empty_history(db_session):
    store_a, store_b, supervisor, _, product_a, product_b = _setup(db_session)
    request = _request(supervisor)

    local_mapping = models.InventoryExternalProductMapping(
        store_id=store_a.id, source="ERP", external_product_id="local-1",
        external_sku="LOCAL-1", product_id=product_a.id, active=True,
        created_by_user_id=supervisor.id, updated_by_user_id=supervisor.id,
    )
    foreign_mapping = models.InventoryExternalProductMapping(
        store_id=store_b.id, source="ERP", external_product_id="foreign-1",
        external_sku="FOREIGN-1", product_id=product_b.id, active=True,
        created_by_user_id=supervisor.id, updated_by_user_id=supervisor.id,
    )
    db_session.add_all([local_mapping, foreign_mapping])
    db_session.flush()
    db_session.add(models.InventoryExternalProductMappingEvent(
        mapping_id=foreign_mapping.id, actor_user_id=supervisor.id,
        event_type="CREATED", before_state=None,
        after_state={"store_id": store_b.id, "product_id": product_b.id},
        reason="Foreign mapping fixture",
    ))
    db_session.commit()

    # A valid mapping without audit events is distinguishable from a
    # foreign/nonexistent mapping and must return an empty history.
    local_history = main_module.list_inventory_external_product_mapping_events(
        store_a.id, local_mapping.id, request, db_session,
    )
    assert local_history == {"mapping_id": local_mapping.id, "items": []}

    # Supplying a foreign mapping ID under the caller's own store path must
    # not disclose its audit events.
    with pytest.raises(HTTPException) as foreign:
        main_module.list_inventory_external_product_mapping_events(
            store_a.id, foreign_mapping.id, request, db_session,
        )
    assert foreign.value.status_code == 404

    with pytest.raises(HTTPException) as missing:
        main_module.list_inventory_external_product_mapping_events(
            store_a.id, foreign_mapping.id + 100000, request, db_session,
        )
    assert missing.value.status_code == 404
