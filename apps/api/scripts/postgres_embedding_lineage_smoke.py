"""Verify PostgreSQL SKU embedding exemplar source lineage is immutable."""

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.database import SessionLocal
from scripts.postgres_embedding_retention_smoke import _create_fixture


def assert_rejected(statement: str, params: dict, description: str) -> None:
    with SessionLocal() as db:
        try:
            db.execute(text(statement), params)
            db.commit()
        except DBAPIError:
            db.rollback()
            return
    raise AssertionError(f"PostgreSQL allowed forbidden embedding lineage operation: {description}")


def main() -> None:
    suffix = uuid4().hex[:8]
    source_image_id, _target_image_id, product_id = _create_fixture(suffix)

    with SessionLocal() as db:
        exemplar_id = db.execute(
            text(
                "SELECT id FROM product_embedding_exemplars "
                "WHERE shelf_image_id = :image_id"
            ),
            {"image_id": source_image_id},
        ).scalar_one()
        reviewer_id = db.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": f"pg-embed-reviewer-{suffix}@example.test"},
        ).scalar_one()
        image_sha256 = db.execute(
            text("SELECT sha256 FROM shelf_images WHERE id = :id"),
            {"id": source_image_id},
        ).scalar_one()

    assert_rejected(
        "UPDATE product_embedding_exemplars SET shelf_image_id = NULL WHERE id = :id",
        {"id": exemplar_id},
        "detaching the source image",
    )
    assert_rejected(
        "UPDATE product_embedding_exemplars SET image_sha256 = :digest WHERE id = :id",
        {"id": exemplar_id, "digest": "c" * 64},
        "changing the source digest",
    )
    assert_rejected(
        "UPDATE product_embedding_exemplars SET embedding = '[0.0, 1.0, 0.0]'::json "
        "WHERE id = :id",
        {"id": exemplar_id},
        "changing the derived embedding",
    )
    assert_rejected(
        """
        INSERT INTO product_embedding_exemplars
            (product_id, shelf_image_id, embedding, embedding_dimension,
             model_version, image_sha256, licence, review_status,
             created_by_user_id, reviewed_by_user_id, reviewed_at, created_at)
        VALUES
            (:product_id, :image_id, '[1.0, 0.0, 0.0]'::json, 3,
             :model_version, :digest, 'smoke-test', 'PENDING',
             :reviewer_id, NULL, NULL, now())
        """,
        {
            "product_id": product_id,
            "image_id": source_image_id,
            "model_version": f"invalid-sha-{suffix}",
            "digest": "d" * 64,
            "reviewer_id": reviewer_id,
        },
        "inserting an exemplar with a mismatched image digest",
    )

    with SessionLocal() as db:
        db.execute(
            text("UPDATE product_embedding_exemplars SET review_status = 'REJECTED', "
                 "review_notes = 'lineage smoke review update' WHERE id = :id"),
            {"id": exemplar_id},
        )
        db.commit()
        review_status = db.execute(
            text("SELECT review_status FROM product_embedding_exemplars WHERE id = :id"),
            {"id": exemplar_id},
        ).scalar_one()
    assert review_status == "REJECTED", "review fields should remain mutable through the review lifecycle"

    with SessionLocal() as db:
        db.execute(
            text("UPDATE shelf_images SET retention_status = 'RESTRICTED' WHERE id = :id"),
            {"id": source_image_id},
        )
        db.commit()

    assert_rejected(
        """
        INSERT INTO product_embedding_exemplars
            (product_id, shelf_image_id, embedding, embedding_dimension,
             model_version, image_sha256, licence, review_status,
             created_by_user_id, created_at)
        VALUES
            (:product_id, :image_id, '[1.0, 0.0, 0.0]'::json, 3,
             :model_version, :digest, 'smoke-test', 'PENDING',
             :reviewer_id, now())
        """,
        {
            "product_id": product_id,
            "image_id": source_image_id,
            "model_version": f"restricted-source-{suffix}",
            "digest": image_sha256,
            "reviewer_id": reviewer_id,
        },
        "inserting an exemplar from a restricted source image",
    )


if __name__ == "__main__":
    main()
