"""Exercise concurrent task creation through the API against migrated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app


def assert_task_creation_audit(
    client: TestClient,
    task_id: int,
    expected_event_types: tuple[str, ...] = ("CREATED",),
) -> None:
    """Verify the exact atomic audit trail for one successful task creation."""
    response = client.get(f"/api/v1/tasks/{task_id}/events")
    assert response.status_code == 200, response.text
    events = response.json()
    assert [event["event_type"] for event in events] == list(expected_event_types), events
    assert all(event["task_id"] == task_id for event in events)
    assert events[0]["from_status"] is None
    assert events[0]["to_status"] == "PENDING"
    if "APPROVED" in expected_event_types:
        approved_event = next(event for event in events if event["event_type"] == "APPROVED")
        assert approved_event["actual_quantity"] > 0
        assert approved_event["to_status"] == "PENDING"


def main() -> None:
    suffix = uuid4().hex[:12]
    with TestClient(app) as client:
        store_response = client.post(
            "/api/v1/stores",
            json={"code": f"CI-{suffix}", "name": "CI concurrent task smoke"},
        )
        assert store_response.status_code == 201, store_response.text
        store_id = store_response.json()["id"]

        zone_response = client.post(
            "/api/v1/zones", json={"store_id": store_id, "name": "CI zone"},
        )
        assert zone_response.status_code == 201, zone_response.text
        shelf_response = client.post(
            "/api/v1/shelves",
            json={"zone_id": zone_response.json()["id"], "code": f"CI-{suffix}"},
        )
        assert shelf_response.status_code == 201, shelf_response.text
        shelf_id = shelf_response.json()["id"]

        product_response = client.post(
            "/api/v1/products",
            json={"sku": f"CI-SKU-{suffix}", "name": "CI product"},
        )
        assert product_response.status_code == 201, product_response.text
        product_id = product_response.json()["id"]
        assignment_response = client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": shelf_id,
                "product_id": product_id,
                "target_quantity": 10,
                "min_display_quantity": 2,
            },
        )
        assert assignment_response.status_code == 201, assignment_response.text

        payload = {
            "store_id": store_id,
            "shelf_id": shelf_id,
            "product_id": product_id,
            "requested_quantity": 2,
        }
        barrier = Barrier(2)

        def create_task():
            barrier.wait(timeout=10)
            return client.post("/api/v1/tasks", json=payload)

        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: create_task(), range(2)))

        created = [response for response in responses if response.status_code == 201]
        conflicts = [response for response in responses if response.status_code == 409]
        assert len(created) == 1, [response.text for response in responses]
        assert len(conflicts) == 1, [response.text for response in responses]
        assert conflicts[0].json()["detail"]["code"] == "ACTIVE_TASK_EXISTS"

        task_id = created[0].json()["id"]
        assert_task_creation_audit(client, task_id)
        assigned = client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": "ASSIGNED", "assigned_to": "CI operator"},
        )
        assert assigned.status_code == 200, assigned.text
        started = client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": "IN_PROGRESS"},
        )
        assert started.status_code == 200, started.text
        completed = client.patch(
            f"/api/v1/tasks/{task_id}/status",
            json={"status": "COMPLETED", "actual_quantity": 2},
        )
        assert completed.status_code == 200, completed.text

        replacement = client.post("/api/v1/tasks", json=payload)
        assert replacement.status_code == 201, replacement.text
        assert_task_creation_audit(client, replacement.json()["id"])

        # Exercise the validated-recommendation creation path against the same
        # PostgreSQL unique index, using a distinct SKU on the existing shelf.
        recommended_product = client.post(
            "/api/v1/products",
            json={"sku": f"CI-REC-{suffix}", "name": "CI recommendation product"},
        )
        assert recommended_product.status_code == 201, recommended_product.text
        recommended_product_id = recommended_product.json()["id"]
        recommended_assignment = client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": shelf_id,
                "product_id": recommended_product_id,
                "target_quantity": 10,
                "min_display_quantity": 2,
            },
        )
        assert recommended_assignment.status_code == 201, recommended_assignment.text
        observation = client.post(
            "/api/v1/observations",
            json={
                "shelf_id": shelf_id,
                "source": "simulation",
                "status": "LOW_STOCK",
                "confidence": 0.99,
                "observed_quantity": 1,
            },
        )
        assert observation.status_code == 201, observation.text
        inventory = client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": recommended_product_id,
                "on_hand_quantity": 20,
                "reserved_quantity": 0,
                "source": "WMS",
            },
        )
        assert inventory.status_code == 201, inventory.text

        recommendation_payload = {
            "store_id": store_id,
            "shelf_id": shelf_id,
            "product_id": recommended_product_id,
            "requested_quantity": 2,
        }
        recommendation_barrier = Barrier(2)

        def create_from_recommendation():
            recommendation_barrier.wait(timeout=10)
            return client.post(
                "/api/v1/tasks/from-recommendation",
                json=recommendation_payload,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            recommendation_responses = list(
                executor.map(lambda _: create_from_recommendation(), range(2))
            )

        recommendation_created = [
            response for response in recommendation_responses
            if response.status_code == 201
        ]
        recommendation_conflicts = [
            response for response in recommendation_responses
            if response.status_code == 409
        ]
        assert len(recommendation_created) == 1, [
            response.text for response in recommendation_responses
        ]
        assert len(recommendation_conflicts) == 1, [
            response.text for response in recommendation_responses
        ]
        assert (
            recommendation_conflicts[0].json()["detail"]["code"]
            == "ACTIVE_TASK_EXISTS"
        )
        assert_task_creation_audit(client, recommendation_created[0].json()["id"])

        # Exercise explicit approval through the operational-decision path.
        decision_product = client.post(
            "/api/v1/products",
            json={"sku": f"CI-DEC-{suffix}", "name": "CI decision product"},
        )
        assert decision_product.status_code == 201, decision_product.text
        decision_product_id = decision_product.json()["id"]
        decision_assignment = client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": shelf_id,
                "product_id": decision_product_id,
                "target_quantity": 12,
                "min_display_quantity": 3,
            },
        )
        assert decision_assignment.status_code == 201, decision_assignment.text
        decision_observation = client.post(
            "/api/v1/observations",
            json={
                "shelf_id": shelf_id,
                "source": "simulation",
                "status": "LOW_STOCK",
                "confidence": 0.99,
                "observed_quantity": 2,
            },
        )
        assert decision_observation.status_code == 201, decision_observation.text
        decision_inventory = client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": decision_product_id,
                "on_hand_quantity": 8,
                "reserved_quantity": 0,
                "source": "WMS",
            },
        )
        assert decision_inventory.status_code == 201, decision_inventory.text

        decision_payload = {
            "store_id": store_id,
            "shelf_id": shelf_id,
            "product_id": decision_product_id,
        }
        decision_barrier = Barrier(2)

        def create_from_operational_decision():
            decision_barrier.wait(timeout=10)
            return client.post(
                "/api/v1/tasks/from-operational-decision?approved=true",
                json=decision_payload,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            decision_responses = list(
                executor.map(lambda _: create_from_operational_decision(), range(2))
            )

        decision_created = [
            response for response in decision_responses
            if response.status_code == 201
        ]
        decision_conflicts = [
            response for response in decision_responses
            if response.status_code == 409
        ]
        assert len(decision_created) == 1, [
            response.text for response in decision_responses
        ]
        assert len(decision_conflicts) == 1, [
            response.text for response in decision_responses
        ]
        assert decision_conflicts[0].json()["detail"]["code"] == "ACTIVE_TASK_EXISTS"
        assert_task_creation_audit(
            client, decision_created[0].json()["id"],
            expected_event_types=("CREATED", "APPROVED"),
        )


        # Validate approved reconciliation under PostgreSQL row-level locking.
        reconciliation_product = client.post(
            "/api/v1/products",
            json={"sku": f"CI-RECON-{suffix}", "name": "CI reconciliation product"},
        )
        assert reconciliation_product.status_code == 201, reconciliation_product.text
        reconciliation_product_id = reconciliation_product.json()["id"]
        reconciliation_assignment = client.post(
            "/api/v1/shelf-products",
            json={
                "shelf_id": shelf_id,
                "product_id": reconciliation_product_id,
                "target_quantity": 10,
                "min_display_quantity": 2,
            },
        )
        assert reconciliation_assignment.status_code == 201, reconciliation_assignment.text
        source_snapshot = client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": reconciliation_product_id,
                "on_hand_quantity": 10,
                "reserved_quantity": 1,
                "source": "WMS",
                "external_reference": f"CI-RECON-SOURCE-{suffix}",
            },
        )
        assert source_snapshot.status_code == 201, source_snapshot.text

        reconciliation_task = client.post(
            "/api/v1/tasks",
            json={
                "store_id": store_id,
                "shelf_id": shelf_id,
                "product_id": reconciliation_product_id,
                "requested_quantity": 2,
            },
        )
        assert reconciliation_task.status_code == 201, reconciliation_task.text
        reconciliation_task_id = reconciliation_task.json()["id"]
        assigned = client.patch(
            f"/api/v1/tasks/{reconciliation_task_id}/status",
            json={"status": "ASSIGNED", "assigned_to": "CI reconciliation operator"},
        )
        assert assigned.status_code == 200, assigned.text
        started = client.patch(
            f"/api/v1/tasks/{reconciliation_task_id}/status",
            json={"status": "IN_PROGRESS"},
        )
        assert started.status_code == 200, started.text
        completed = client.patch(
            f"/api/v1/tasks/{reconciliation_task_id}/status",
            json={"status": "COMPLETED", "actual_quantity": 2},
        )
        assert completed.status_code == 200, completed.text

        actor_db = SessionLocal()
        try:
            actor = models.User(
                email=f"ci-reconciliation-{suffix}@example.test",
                store_id=store_id,
                full_name="CI Reconciliation Supervisor",
                password_hash="ci-only-not-used",
                role="SUPERVISOR",
                is_active=True,
            )
            actor_db.add(actor)
            actor_db.commit()
            actor_db.refresh(actor)
        finally:
            actor_db.close()

        original_request_user = main_module._request_user
        main_module._request_user = lambda db, request: actor
        try:
            reconciliation_barrier = Barrier(2)

            def reconcile_task():
                reconciliation_barrier.wait(timeout=10)
                return client.post(
                    f"/api/v1/tasks/{reconciliation_task_id}/reconcile-inventory",
                    json={"reason": "CI supervisor confirmed physical refill."},
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                reconciliation_responses = list(
                    executor.map(lambda _: reconcile_task(), range(2))
                )
        finally:
            main_module._request_user = original_request_user

        reconciliation_created = [
            response for response in reconciliation_responses
            if response.status_code == 201
        ]
        reconciliation_conflicts = [
            response for response in reconciliation_responses
            if response.status_code == 409
        ]
        assert len(reconciliation_created) == 1, [
            response.text for response in reconciliation_responses
        ]
        assert len(reconciliation_conflicts) == 1, [
            response.text for response in reconciliation_responses
        ]
        assert (
            reconciliation_conflicts[0].json()["detail"]["code"]
            == "INVENTORY_ALREADY_RECONCILED"
        )
        movement_id = reconciliation_created[0].json()["id"]
        result_snapshot_id = reconciliation_created[0].json()["result_snapshot_id"]

        inventory_history = client.get(
            "/api/v1/inventory/snapshots",
            params={"store_id": store_id, "product_id": reconciliation_product_id},
        )
        assert inventory_history.status_code == 200, inventory_history.text
        history_by_id = {item["id"]: item for item in inventory_history.json()}
        original_snapshot_id = source_snapshot.json()["id"]
        assert history_by_id[original_snapshot_id]["on_hand_quantity"] == 10
        assert history_by_id[result_snapshot_id]["on_hand_quantity"] == 8
        assert history_by_id[result_snapshot_id]["reserved_quantity"] == 1

        reconciliation_events = client.get(
            f"/api/v1/tasks/{reconciliation_task_id}/events"
        )
        assert reconciliation_events.status_code == 200, reconciliation_events.text
        assert [
            event["event_type"] for event in reconciliation_events.json()
        ].count("INVENTORY_RECONCILED") == 1

        # The PostgreSQL migration installs database-level append-only triggers.
        audit_db = SessionLocal()
        try:
            for statement in (
                "UPDATE inventory_movements SET reason = 'tampered' WHERE id = :movement_id",
                "DELETE FROM inventory_movements WHERE id = :movement_id",
            ):
                try:
                    audit_db.execute(text(statement), {"movement_id": movement_id})
                    audit_db.commit()
                except DBAPIError:
                    audit_db.rollback()
                else:
                    raise AssertionError("inventory_movements accepted an UPDATE or DELETE")
            assert (
                audit_db.query(models.InventoryMovement)
                .filter(models.InventoryMovement.id == movement_id)
                .count()
                == 1
            )
        finally:
            audit_db.close()

        print(
            "PostgreSQL concurrent task creation: PASS "
            "(three task-creation paths and approved reconciliation each return one 201 and one 409; "
            "audit is unique, snapshots are immutable and inventory movements reject UPDATE/DELETE)"
        )


if __name__ == "__main__":
    main()
