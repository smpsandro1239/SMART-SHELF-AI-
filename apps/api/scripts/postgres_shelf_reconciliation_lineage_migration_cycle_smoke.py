"""Exercise PostgreSQL 0099 downgrade and re-apply in an isolated database."""

import os
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


UP_REVISION = "0099_shelf_reconciliation_lineage"
DOWN_REVISION = "0098_shelf_operational_evidence_retention"

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

        print(
            "PostgreSQL 0099 migration-cycle smoke passed: isolated database "
            "upgraded to 0099, downgraded to 0098 with all six triggers and "
            "five functions removed, then re-applied 0099 successfully."
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
