"""Verify PostgreSQL append-only triggers for external artifact declarations and inventories."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from scripts.postgres_artifact_consumption_smoke import create_fixture


def assert_statement_rejected(statement: str, params: dict, description: str) -> None:
    with SessionLocal() as db:
        try:
            db.execute(text(statement), params)
            db.commit()
        except DBAPIError:
            db.rollback()
            return
    raise AssertionError(f"PostgreSQL allowed forbidden mutation: {description}")


def main() -> None:
    suffix = uuid4().hex[:8]
    payload = f"artifact immutability smoke {suffix}".encode()
    image_id, artifact_id, store_id, _integration_id = create_fixture(suffix, payload)

    with SessionLocal() as db:
        snapshot_id = db.execute(
            text(
                "SELECT id FROM shelf_image_artifact_inventory_snapshots "
                "WHERE shelf_image_id = :image_id AND store_id = :store_id"
            ),
            {"image_id": image_id, "store_id": store_id},
        ).scalar_one()

    assert_statement_rejected(
        "UPDATE shelf_image_artifact_references SET sha256 = sha256 WHERE id = :id",
        {"id": artifact_id},
        "artifact reference UPDATE",
    )
    assert_statement_rejected(
        "DELETE FROM shelf_image_artifact_references WHERE id = :id",
        {"id": artifact_id},
        "artifact reference DELETE",
    )
    assert_statement_rejected(
        "UPDATE shelf_image_artifact_inventory_snapshots "
        "SET manifest_sha256 = manifest_sha256 WHERE id = :id",
        {"id": snapshot_id},
        "inventory snapshot UPDATE",
    )
    assert_statement_rejected(
        "DELETE FROM shelf_image_artifact_inventory_snapshots WHERE id = :id",
        {"id": snapshot_id},
        "inventory snapshot DELETE",
    )

    with SessionLocal() as db:
        reference_count = db.execute(
            text("SELECT count(*) FROM shelf_image_artifact_references WHERE id = :id"),
            {"id": artifact_id},
        ).scalar_one()
        snapshot_count = db.execute(
            text("SELECT count(*) FROM shelf_image_artifact_inventory_snapshots WHERE id = :id"),
            {"id": snapshot_id},
        ).scalar_one()
    assert reference_count == 1, "artifact reference disappeared after rejected mutations"
    assert snapshot_count == 1, "inventory snapshot disappeared after rejected mutations"


if __name__ == "__main__":
    main()
