"""Verify concurrent first-admin bootstrap is serialized by PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient

from app import main as main_module, models
from app.database import SessionLocal
from app.main import app


def main() -> None:
    original_settings = main_module.settings
    bootstrap_key = f"bootstrap-smoke-{uuid4().hex}-private"
    main_module.settings = original_settings.model_copy(
        update={"app_env": "test", "bootstrap_admin_key": bootstrap_key}
    )

    suffix = uuid4().hex[:12]
    try:
        with TestClient(app) as client:
            barrier = Barrier(2)

            def submit(index: int):
                barrier.wait(timeout=10)
                return client.post(
                    "/api/v1/auth/bootstrap",
                    headers={"X-Bootstrap-Key": bootstrap_key},
                    json={
                        "email": f"bootstrap-{suffix}-{index}@example.test",
                        "full_name": f"Bootstrap Admin {index}",
                        "password": f"Strong-password-{index}-42!",
                    },
                )

            with ThreadPoolExecutor(max_workers=2) as executor:
                responses = list(executor.map(submit, (1, 2)))

        created = [response for response in responses if response.status_code == 201]
        conflicts = [response for response in responses if response.status_code == 409]
        assert len(created) == 1, [
            (response.status_code, response.text) for response in responses
        ]
        assert len(conflicts) == 1, [
            (response.status_code, response.text) for response in responses
        ]

        with SessionLocal() as db:
            admins = db.query(models.User).filter(
                models.User.email.like(f"bootstrap-{suffix}-%@example.test"),
                models.User.role == "ADMIN",
            ).count()
            assert admins == 1, f"Expected one bootstrapped administrator, found {admins}"
    finally:
        main_module.settings = original_settings

    print(
        "PostgreSQL concurrent admin bootstrap smoke passed: one request created "
        "the administrator, the competing request received 409, and exactly "
        "one administrator persisted."
    )


if __name__ == "__main__":
    main()
