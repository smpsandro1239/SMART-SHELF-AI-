"""Verify PostgreSQL enforces manual inventory count provenance and immutability."""

from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app
from app.security import create_access_token


def _expect_rejected(db, statement: str, parameters: dict, description: str) -> None:
    try:
        db.execute(text(statement), parameters)
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        if "provenance mismatch" not in str(exc.orig):
            raise AssertionError(
                f"PostgreSQL rejected {description} for an unexpected reason: {exc.orig}"
            ) from exc
    else:
        raise AssertionError(f"PostgreSQL accepted invalid manual-count {description}")


def main() -> None:
    suffix = uuid4().hex[:10]
    with TestClient(app) as client:
        store_a = client.post(
            "/api/v1/stores",
            json={"code": f"PG-MANUAL-A-{suffix}", "name": "Manual count store A"},
        )
        store_b = client.post(
            "/api/v1/stores",
            json={"code": f"PG-MANUAL-B-{suffix}", "name": "Manual count store B"},
        )
        product = client.post(
            "/api/v1/products",
            json={"sku": f"PG-MANUAL-SKU-{suffix}", "name": "Manual count product"},
        )
        assert store_a.status_code == 201, store_a.text
        assert store_b.status_code == 201, store_b.text
        assert product.status_code == 201, product.text
        store_a_id = store_a.json()["id"]
        store_b_id = store_b.json()["id"]
        product_id = product.json()["id"]

        with SessionLocal() as db:
            actors = {
                "supervisor": models.User(
                    email=f"pg-manual-supervisor-{suffix}@example.test",
                    full_name="Manual count supervisor",
                    password_hash="smoke-test-only",
                    role="SUPERVISOR",
                    store_id=store_a_id,
                    is_active=True,
                ),
                "other_store": models.User(
                    email=f"pg-manual-other-{suffix}@example.test",
                    full_name="Other store supervisor",
                    password_hash="smoke-test-only",
                    role="SUPERVISOR",
                    store_id=store_b_id,
                    is_active=True,
                ),
                "inactive": models.User(
                    email=f"pg-manual-inactive-{suffix}@example.test",
                    full_name="Inactive supervisor",
                    password_hash="smoke-test-only",
                    role="SUPERVISOR",
                    store_id=store_a_id,
                    is_active=False,
                ),
                "employee": models.User(
                    email=f"pg-manual-employee-{suffix}@example.test",
                    full_name="Manual count employee",
                    password_hash="smoke-test-only",
                    role="EMPLOYEE",
                    store_id=store_a_id,
                    is_active=True,
                ),
                "admin": models.User(
                    email=f"pg-manual-admin-{suffix}@example.test",
                    full_name="Global manual count admin",
                    password_hash="smoke-test-only",
                    role="ADMIN",
                    store_id=None,
                    is_active=True,
                ),
            }
            db.add_all(actors.values())
            db.commit()
            actor_ids = {key: actor.id for key, actor in actors.items()}

        token = create_access_token(
            user_id=actor_ids["supervisor"], role="SUPERVISOR"
        )[0]
        headers = {"Authorization": f"Bearer {token}"}
        original_settings = main_module.settings
        main_module.settings = original_settings.model_copy(update={"app_env": "production"})
        try:
            manual = client.post(
                "/api/v1/inventory/snapshots",
                json={
                    "store_id": store_a_id,
                    "product_id": product_id,
                    "on_hand_quantity": 12,
                    "reserved_quantity": 0,
                    "source": "MANUAL",
                    "reason": "PostgreSQL audit smoke manual count",
                },
                headers=headers,
            )
        finally:
            main_module.settings = original_settings
        assert manual.status_code == 201, manual.text
        manual_snapshot_id = manual.json()["id"]

        wms = client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_a_id,
                "product_id": product_id,
                "on_hand_quantity": 10,
                "reserved_quantity": 0,
                "source": "WMS",
                "external_reference": f"PG-MANUAL-WMS-{suffix}",
                "location_code": "BACKROOM-MANUAL-CI",
                "availability_status": "AVAILABLE",
            },
        )
        assert wms.status_code == 201, wms.text
        wms_snapshot_id = wms.json()["id"]

    insert_event = """
        INSERT INTO inventory_manual_count_events
            (snapshot_id, store_id, product_id, actor_user_id, reason, created_at)
        VALUES
            (:snapshot_id, :store_id, :product_id, :actor_id,
             'Direct PostgreSQL provenance smoke', CURRENT_TIMESTAMP)
    """
    base = {
        "snapshot_id": manual_snapshot_id,
        "store_id": store_a_id,
        "product_id": product_id,
    }

    with SessionLocal() as db:
        # A global active ADMIN is valid at the database boundary.
        db.execute(
            text(insert_event),
            {**base, "actor_id": actor_ids["admin"]},
        )
        db.commit()

        for key, description in (
            ("other_store", "cross-store supervisor"),
            ("inactive", "inactive supervisor"),
            ("employee", "employee actor"),
        ):
            _expect_rejected(
                db,
                insert_event,
                {**base, "actor_id": actor_ids[key]},
                description,
            )

        _expect_rejected(
            db,
            insert_event,
            {
                **base,
                "snapshot_id": wms_snapshot_id,
                "actor_id": actor_ids["supervisor"],
            },
            "non-MANUAL snapshot",
        )

        event_id = db.execute(
            text(
                "SELECT id FROM inventory_manual_count_events "
                "WHERE snapshot_id = :snapshot_id ORDER BY id LIMIT 1"
            ),
            {"snapshot_id": manual_snapshot_id},
        ).scalar_one()

        for statement in (
            "UPDATE inventory_manual_count_events SET reason='tampered' WHERE id=:id",
            "DELETE FROM inventory_manual_count_events WHERE id=:id",
        ):
            try:
                db.execute(text(statement), {"id": event_id})
                db.commit()
            except DBAPIError:
                db.rollback()
            else:
                raise AssertionError(
                    "PostgreSQL allowed an inventory manual count event mutation"
                )

        event_count = db.execute(
            text(
                "SELECT COUNT(*) FROM inventory_manual_count_events "
                "WHERE snapshot_id = :snapshot_id"
            ),
            {"snapshot_id": manual_snapshot_id},
        ).scalar_one()
        assert event_count == 2, event_count

    print(
        "PostgreSQL manual count audit smoke passed: active same-store SUPERVISOR "
        "and global ADMIN accepted; inactive, EMPLOYEE, cross-store and non-MANUAL "
        "provenance rejected; audit events remain append-only."
    )


if __name__ == "__main__":
    main()
