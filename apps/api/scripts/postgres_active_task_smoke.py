"""Exercise concurrent task creation through the API against migrated PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


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

        print(
            "PostgreSQL concurrent task creation: PASS "
            "(manual, recommendation and approved operational-decision paths "
            "each return one 201 and one 409; terminal task releases the unique slot)"
        )


if __name__ == "__main__":
    main()
