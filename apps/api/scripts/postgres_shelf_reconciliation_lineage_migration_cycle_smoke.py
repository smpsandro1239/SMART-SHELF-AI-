"""Exercise PostgreSQL 0099 downgrade and re-apply in an isolated database."""

import os
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


UP_REVISION = "0099_shelf_reconciliation_lineage"
DOWN_REVISION = "0098_shelf_operational_evidence_retention"
EMBEDDING_UP_REVISION = "0100_embedding_source_image_shelf_lineage"
EMBEDDING_TRIGGER = "trg_shelf_image_embedding_shelf_lineage_0100"
EMBEDDING_FUNCTION = "prevent_embedding_source_image_shelf_change_0100"

TRIGGERS = (
    "trg_observation_alert_shelf_lineage_0099",
    "trg_inventory_reconciliation_lineage_0099",
    "trg_referenced_shelf_product_change_0099",
    "trg_referenced_observation_change_0099",
    "trg_zone_shelf_evidence_lineage_0099",
    "trg_shelf_shelf_evidence_lineage_0099",
)
FUNCTIONS = (
    "enforce_shelf_alert_lineage_0099",
    "enforce_reconciliation_lineage_0099",
    "prevent_referenced_shelf_product_change_0099",
    "prevent_referenced_observation_change_0099",
    "prevent_referenced_shelf_hierarchy_change_0099",
)


def _assert_revision(engine, expected: str) -> None:
    with engine.connect() as connection:
        actual = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    assert actual == expected, f"expected Alembic revision {expected}, got {actual}"


def _assert_objects(engine, *, expected: bool) -> None:
    trigger_names = ", ".join(f"'{name}'" for name in TRIGGERS)
    function_names = ", ".join(f"'{name}'" for name in FUNCTIONS)
    with engine.connect() as connection:
        trigger_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM pg_trigger "
                "WHERE NOT tgisinternal AND tgname IN (" + trigger_names + ")"
            )
        ).scalar_one()
        function_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM pg_proc "
                "WHERE pg_function_is_visible(oid) AND proname IN ("
                + function_names
                + ")"
            )
        ).scalar_one()
    expected_count = len(TRIGGERS) if expected else 0
    expected_functions = len(FUNCTIONS) if expected else 0
    assert trigger_count == expected_count, (
        f"expected {expected_count} migration 0099 triggers, got {trigger_count}"
    )
    assert function_count == expected_functions, (
        f"expected {expected_functions} migration 0099 functions, got {function_count}"
    )


def _assert_embedding_image_objects(engine, *, expected: bool) -> None:
    with engine.connect() as connection:
        trigger_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM pg_trigger "
                "WHERE NOT tgisinternal AND tgname = :name"
            ),
            {"name": EMBEDDING_TRIGGER},
        ).scalar_one()
        function_count = connection.execute(
            text(
                "SELECT COUNT(*) FROM pg_proc "
                "WHERE pg_function_is_visible(oid) AND proname = :name"
            ),
            {"name": EMBEDDING_FUNCTION},
        ).scalar_one()
    expected_count = 1 if expected else 0
    assert trigger_count == expected_count, (
        f"expected {expected_count} migration 0100 trigger(s), got {trigger_count}"
    )
    assert function_count == expected_count, (
        f"expected {expected_count} migration 0100 function(s), got {function_count}"
    )


def main() -> None:
    configured_url = os.environ.get("DATABASE_URL")
    if not configured_url:
        raise RuntimeError("DATABASE_URL is required")
    base_url = make_url(configured_url)
    if base_url.get_backend_name() != "postgresql":
        raise RuntimeError("this smoke requires PostgreSQL")

    database_name = f"smart_shelf_0099_cycle_{uuid4().hex[:8]}"
    admin_engine = create_engine(
        base_url.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    target_engine = None
    try:
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{database_name}"')

        target_url = base_url.set(database=database_name)
        os.environ["DATABASE_URL"] = target_url.render_as_string(hide_password=False)
        config = Config("alembic.ini")

        command.upgrade(config, UP_REVISION)
        target_engine = create_engine(target_url)
        _assert_revision(target_engine, UP_REVISION)
        _assert_objects(target_engine, expected=True)

        command.downgrade(config, DOWN_REVISION)
        _assert_revision(target_engine, DOWN_REVISION)
        _assert_objects(target_engine, expected=False)

        command.upgrade(config, UP_REVISION)
        _assert_revision(target_engine, UP_REVISION)
        _assert_objects(target_engine, expected=True)

        command.upgrade(config, EMBEDDING_UP_REVISION)
        _assert_revision(target_engine, EMBEDDING_UP_REVISION)
        _assert_objects(target_engine, expected=True)
        _assert_embedding_image_objects(target_engine, expected=True)

        command.downgrade(config, UP_REVISION)
        _assert_revision(target_engine, UP_REVISION)
        _assert_objects(target_engine, expected=True)
        _assert_embedding_image_objects(target_engine, expected=False)

        command.upgrade(config, EMBEDDING_UP_REVISION)
        _assert_revision(target_engine, EMBEDDING_UP_REVISION)
        _assert_objects(target_engine, expected=True)
        _assert_embedding_image_objects(target_engine, expected=True)

        print(
            "PostgreSQL migration-cycle smoke passed: isolated database "
            "upgraded through 0099 and 0100; 0099 downgrade/re-apply removed "
            "and restored its six triggers/five functions; 0100 downgrade/"
            "re-apply removed and restored its source-image shelf-lineage "
            "trigger/function."
        )
    finally:
        if target_engine is not None:
            target_engine.dispose()
        with admin_engine.connect() as connection:
            connection.exec_driver_sql(
                f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)'
            )
        admin_engine.dispose()


if __name__ == "__main__":
    main()
