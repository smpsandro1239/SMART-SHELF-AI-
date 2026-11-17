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
        replacement_task_id = replacement.json()["id"]
        assert_task_creation_audit(client, replacement_task_id)

        # Two operators racing to assign the same task must create one
        # transition event only. PostgreSQL row locking serializes the writes.
        transition_barrier = Barrier(2)

        def assign_replacement_task():
            transition_barrier.wait(timeout=10)
            return client.patch(
                f"/api/v1/tasks/{replacement_task_id}/status",
                json={"status": "ASSIGNED", "assigned_to": "CI lifecycle operator"},
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            transition_responses = list(
                executor.map(lambda _: assign_replacement_task(), range(2))
            )

        transition_successes = [
            response for response in transition_responses if response.status_code == 200
        ]
        transition_conflicts = [
            response for response in transition_responses if response.status_code == 409
        ]
        assert len(transition_successes) == 1, [
            response.text for response in transition_responses
        ]
        assert len(transition_conflicts) == 1, [
            response.text for response in transition_responses
        ]

        started_replacement = client.patch(
            f"/api/v1/tasks/{replacement_task_id}/status",
            json={"status": "IN_PROGRESS"},
        )
        assert started_replacement.status_code == 200, started_replacement.text
        completed_replacement = client.patch(
            f"/api/v1/tasks/{replacement_task_id}/status",
            json={"status": "COMPLETED", "actual_quantity": 2},
        )
        assert completed_replacement.status_code == 200, completed_replacement.text
        lifecycle_events = client.get(
            f"/api/v1/tasks/{replacement_task_id}/events"
        )
        assert lifecycle_events.status_code == 200, lifecycle_events.text
        lifecycle_audit = lifecycle_events.json()
        assert [event["event_type"] for event in lifecycle_audit] == [
            "CREATED", "STATUS_CHANGED", "STATUS_CHANGED", "STATUS_CHANGED",
        ]
        assert [
            (event["from_status"], event["to_status"])
            for event in lifecycle_audit
        ] == [
            (None, "PENDING"),
            ("PENDING", "ASSIGNED"),
            ("ASSIGNED", "IN_PROGRESS"),
            ("IN_PROGRESS", "COMPLETED"),
        ]
        assert len({event["id"] for event in lifecycle_audit}) == 4

        # Cancellation must be a single audited transition and release the active-task key.
        cancellation_task = client.post("/api/v1/tasks", json=payload)
        assert cancellation_task.status_code == 201, cancellation_task.text
        cancellation_task_id = cancellation_task.json()["id"]
        cancelled = client.patch(
            f"/api/v1/tasks/{cancellation_task_id}/status",
            json={"status": "CANCELLED", "exception_reason": "CI cancellation lifecycle"},
        )
        assert cancelled.status_code == 200, cancelled.text
        repeated_cancel = client.patch(
            f"/api/v1/tasks/{cancellation_task_id}/status",
            json={"status": "CANCELLED", "exception_reason": "CI duplicate cancellation"},
        )
        assert repeated_cancel.status_code == 409, repeated_cancel.text
        cancellation_events = client.get(
            f"/api/v1/tasks/{cancellation_task_id}/events"
        )
        assert cancellation_events.status_code == 200, cancellation_events.text
        cancellation_audit = cancellation_events.json()
        assert [event["event_type"] for event in cancellation_audit] == [
            "CREATED", "STATUS_CHANGED",
        ]
        assert [
            (event["from_status"], event["to_status"])
            for event in cancellation_audit
        ] == [(None, "PENDING"), ("PENDING", "CANCELLED")]
        assert cancellation_audit[-1]["reason"] == "CI cancellation lifecycle"
        assert len({event["id"] for event in cancellation_audit}) == 2

        # An audit failure after flush must roll back both the state change
        # and the inserted event on PostgreSQL, not just in SQLite unit tests.
        rollback_task = client.post("/api/v1/tasks", json=payload)
        assert rollback_task.status_code == 201, rollback_task.text
        rollback_task_id = rollback_task.json()["id"]
        original_record_task_event = main_module._record_task_event

        def fail_status_audit_after_flush(db, task, event_type, actor, **kwargs):
            original_record_task_event(db, task, event_type, actor, **kwargs)
            if event_type == "STATUS_CHANGED":
                db.flush()
                raise RuntimeError("CI forced task lifecycle audit failure after flush")

        main_module._record_task_event = fail_status_audit_after_flush
        try:
            with TestClient(app, raise_server_exceptions=False) as rollback_client:
                rollback_response = rollback_client.patch(
                    f"/api/v1/tasks/{rollback_task_id}/status",
                    json={"status": "ASSIGNED", "assigned_to": "CI rollback operator"},
                )
        finally:
            main_module._record_task_event = original_record_task_event
        assert rollback_response.status_code == 500, rollback_response.text

        rollback_db = SessionLocal()
        try:
            rolled_back_task = rollback_db.get(
                models.ReplenishmentTask, rollback_task_id
            )
            assert rolled_back_task is not None
            assert rolled_back_task.status == "PENDING"
            rollback_events = (
                rollback_db.query(models.ReplenishmentTaskEvent)
                .filter(models.ReplenishmentTaskEvent.task_id == rollback_task_id)
                .order_by(models.ReplenishmentTaskEvent.id)
                .all()
            )
            assert [event.event_type for event in rollback_events] == ["CREATED"]
        finally:
            rollback_db.close()

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
                "product_id": recommended_product_id,
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
                "product_id": decision_product_id,
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
            freshness_policy = client.post(
                "/api/v1/inventory/freshness-policies",
                json={
                    "store_id": store_id,
                    "source": "WMS",
                    "max_age_minutes": 360,
                },
            )
            assert freshness_policy.status_code == 200, freshness_policy.text
            assert freshness_policy.json()["max_age_minutes"] == 360

            listed_policies = client.get(
                "/api/v1/inventory/freshness-policies",
                params={"store_id": store_id},
            )
            assert listed_policies.status_code == 200, listed_policies.text
            assert any(
                item["source"] == "WMS" and item["max_age_minutes"] == 360
                for item in listed_policies.json()
            )

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


        # Force an audit failure after both inventory rows have been flushed.
        # The movement, result snapshot and task event must all roll back.
        rollback_task = client.post(
            "/api/v1/tasks",
            json={
                "store_id": store_id,
                "shelf_id": shelf_id,
                "product_id": reconciliation_product_id,
                "requested_quantity": 1,
            },
        )
        assert rollback_task.status_code == 201, rollback_task.text
        rollback_task_id = rollback_task.json()["id"]
        rollback_assigned = client.patch(
            f"/api/v1/tasks/{rollback_task_id}/status",
            json={"status": "ASSIGNED", "assigned_to": "CI rollback operator"},
        )
        assert rollback_assigned.status_code == 200, rollback_assigned.text
        rollback_started = client.patch(
            f"/api/v1/tasks/{rollback_task_id}/status",
            json={"status": "IN_PROGRESS"},
        )
        assert rollback_started.status_code == 200, rollback_started.text
        rollback_completed = client.patch(
            f"/api/v1/tasks/{rollback_task_id}/status",
            json={"status": "COMPLETED", "actual_quantity": 1},
        )
        assert rollback_completed.status_code == 200, rollback_completed.text

        original_record_task_event = main_module._record_task_event

        def fail_reconciliation_audit(db, task, event_type, actor, **kwargs):
            if event_type == "INVENTORY_RECONCILED":
                raise RuntimeError("CI forced failure before reconciliation commit")
            return original_record_task_event(db, task, event_type, actor, **kwargs)

        main_module._request_user = lambda db, request: actor
        main_module._record_task_event = fail_reconciliation_audit
        try:
            with TestClient(app, raise_server_exceptions=False) as rollback_client:
                rollback_response = rollback_client.post(
                    f"/api/v1/tasks/{rollback_task_id}/reconcile-inventory",
                    json={"reason": "CI rollback atomicity test."},
                )
        finally:
            main_module._request_user = original_request_user
            main_module._record_task_event = original_record_task_event

        assert rollback_response.status_code == 500, rollback_response.text
        rollback_db = SessionLocal()
        try:
            assert (
                rollback_db.query(models.InventoryMovement)
                .filter(models.InventoryMovement.task_id == rollback_task_id)
                .count()
                == 0
            )
            assert (
                rollback_db.query(models.InventorySnapshot)
                .filter(
                    models.InventorySnapshot.store_id == store_id,
                    models.InventorySnapshot.product_id == reconciliation_product_id,
                )
                .count()
                == 2
            )
            assert (
                rollback_db.query(models.ReplenishmentTaskEvent)
                .filter(
                    models.ReplenishmentTaskEvent.task_id == rollback_task_id,
                    models.ReplenishmentTaskEvent.event_type == "INVENTORY_RECONCILED",
                )
                .count()
                == 0
            )
        finally:
            rollback_db.close()

        # Verify the retention-event check constraint accepts legal-hold events
        # and that the database-level append-only trigger protects them.
        retention_db = SessionLocal()
        try:
            retention_image = models.ShelfImage(
                shelf_id=shelf_id,
                original_filename="retention-smoke.jpg",
                storage_path=f"/tmp/retention-smoke-{suffix}.jpg",
                mime_type="image/jpeg",
                file_size_bytes=1,
                sha256="b" * 64,
                analysis_status="PENDING",
                legal_hold=True,
            )
            retention_db.add(retention_image)
            retention_db.flush()
            retention_events = [
                models.ShelfImageRetentionEvent(
                    shelf_image_id=retention_image.id,
                    event_type=event_type,
                    from_status="ACTIVE",
                    to_status="ACTIVE",
                    actor_user_id=None,
                    reason="PostgreSQL legal-hold audit smoke",
                )
                for event_type in ("LEGAL_HOLD_APPLIED", "LEGAL_HOLD_RELEASED")
            ]
            retention_db.add_all(retention_events)
            retention_db.commit()
            retention_event_id = retention_events[0].id

            for statement in (
                "UPDATE shelf_image_retention_events SET reason = 'tampered' WHERE id = :event_id",
                "DELETE FROM shelf_image_retention_events WHERE id = :event_id",
            ):
                try:
                    retention_db.execute(text(statement), {"event_id": retention_event_id})
                    retention_db.commit()
                except DBAPIError:
                    retention_db.rollback()
                else:
                    raise AssertionError("shelf_image_retention_events accepted an UPDATE or DELETE")

            assert (
                retention_db.query(models.ShelfImageRetentionEvent)
                .filter(models.ShelfImageRetentionEvent.shelf_image_id == retention_image.id)
                .count()
                == 2
            )
        finally:
            retention_db.close()

        # Two different completed tasks must not spend the same backroom
        # snapshot twice. They deliberately share one product and source
        # snapshot but belong to separate shelves, so the active-task index
        # does not serialize their creation.
        contention_zone = client.post(
            "/api/v1/zones",
            json={"store_id": store_id, "name": f"CI contention zone {suffix}"},
        )
        assert contention_zone.status_code == 201, contention_zone.text
        contention_shelves = []
        for index in (1, 2):
            shelf_response = client.post(
                "/api/v1/shelves",
                json={
                    "zone_id": contention_zone.json()["id"],
                    "code": f"CI-CONT-{suffix}-{index}",
                },
            )
            assert shelf_response.status_code == 201, shelf_response.text
            contention_shelves.append(shelf_response.json()["id"])

        contention_product = client.post(
            "/api/v1/products",
            json={"sku": f"CI-CONT-{suffix}", "name": "CI shared-stock contention product"},
        )
        assert contention_product.status_code == 201, contention_product.text
        contention_product_id = contention_product.json()["id"]
        for contention_shelf_id in contention_shelves:
            assignment = client.post(
                "/api/v1/shelf-products",
                json={
                    "shelf_id": contention_shelf_id,
                    "product_id": contention_product_id,
                    "target_quantity": 8,
                    "min_display_quantity": 1,
                },
            )
            assert assignment.status_code == 201, assignment.text

        contention_source = client.post(
            "/api/v1/inventory/snapshots",
            json={
                "store_id": store_id,
                "product_id": contention_product_id,
                "on_hand_quantity": 5,
                "reserved_quantity": 0,
                "source": "WMS",
                "external_reference": f"CI-CONT-SOURCE-{suffix}",
            },
        )
        assert contention_source.status_code == 201, contention_source.text

        contention_task_ids = []
        for index, contention_shelf_id in enumerate(contention_shelves, start=1):
            task_response = client.post(
                "/api/v1/tasks",
                json={
                    "store_id": store_id,
                    "shelf_id": contention_shelf_id,
                    "product_id": contention_product_id,
                    "requested_quantity": 4,
                },
            )
            assert task_response.status_code == 201, task_response.text
            contention_task_id = task_response.json()["id"]
            contention_task_ids.append(contention_task_id)
            assigned_response = client.patch(
                f"/api/v1/tasks/{contention_task_id}/status",
                json={"status": "ASSIGNED", "assigned_to": f"CI contention operator {index}"},
            )
            assert assigned_response.status_code == 200, assigned_response.text
            started_response = client.patch(
                f"/api/v1/tasks/{contention_task_id}/status",
                json={"status": "IN_PROGRESS"},
            )
            assert started_response.status_code == 200, started_response.text
            completed_response = client.patch(
                f"/api/v1/tasks/{contention_task_id}/status",
                json={"status": "COMPLETED", "actual_quantity": 4},
            )
            assert completed_response.status_code == 200, completed_response.text

        contention_barrier = Barrier(2)

        def reconcile_distinct_task(task_id: int):
            contention_barrier.wait(timeout=10)
            return client.post(
                f"/api/v1/tasks/{task_id}/reconcile-inventory",
                json={"reason": "CI shared-stock concurrency verification."},
            )

        original_request_user_for_contention = main_module._request_user
        main_module._request_user = lambda db, request: actor
        try:
            with ThreadPoolExecutor(max_workers=2) as executor:
                contention_responses = list(
                    executor.map(
                        reconcile_distinct_task,
                        contention_task_ids,
                    )
                )
        finally:
            main_module._request_user = original_request_user_for_contention

        contention_created = [
            response for response in contention_responses
            if response.status_code == 201
        ]
        contention_rejected = [
            response for response in contention_responses
            if response.status_code == 409
        ]
        assert len(contention_created) == 1, [
            response.text for response in contention_responses
        ]
        assert len(contention_rejected) == 1, [
            response.text for response in contention_responses
        ]
        rejected_code = contention_rejected[0].json()["detail"]["code"]
        assert rejected_code in {
            "INVENTORY_EVIDENCE_AFTER_TASK",
            "INSUFFICIENT_BACKROOM_STOCK",
        }, contention_rejected[0].text

        contention_db = SessionLocal()
        try:
            contention_movements = (
                contention_db.query(models.InventoryMovement)
                .filter(
                    models.InventoryMovement.product_id == contention_product_id,
                    models.InventoryMovement.store_id == store_id,
                )
                .all()
            )
            assert len(contention_movements) == 1, len(contention_movements)
            assert float(contention_movements[0].quantity) == 4
            contention_snapshots = (
                contention_db.query(models.InventorySnapshot)
                .filter(
                    models.InventorySnapshot.product_id == contention_product_id,
                    models.InventorySnapshot.store_id == store_id,
                )
                .order_by(models.InventorySnapshot.id)
                .all()
            )
            assert len(contention_snapshots) == 2, len(contention_snapshots)
            assert float(contention_snapshots[-1].on_hand_quantity) == 1
        finally:
            contention_db.close()

        print(
            "PostgreSQL concurrent task creation: PASS "
            "(three task-creation paths and approved reconciliation each return one 201 and one 409; "
            "audit is unique, snapshots are preserved, movement UPDATE/DELETE are blocked and failed reconciliation rolls back atomically)"
        )


if __name__ == "__main__":
    main()
