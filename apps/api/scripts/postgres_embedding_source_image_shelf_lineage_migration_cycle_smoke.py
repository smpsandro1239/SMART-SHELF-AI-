"""Exercise PostgreSQL migration 0100 downgrade and re-apply in an isolated database."""

import os
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


UP_REVISION = "0100_embedding_source_image_shelf_lineage"
DOWN_REVISION = "0099_shelf_reconciliation_lineage"
TRIGGER_0100 = "trg_shelf_image_embedding_shelf_lineage_0100"
FUNCTION_0100 = "prevent_embedding_source_image_shelf_change_0100"
TRIGGERS_0099 = (
    "trg_observation_alert_shelf_lineage_0099",
    "trg_inventory_reconciliation_lineage_0099",
    "trg_referenced_shelf_product_change_0099",
    "trg_referenced_observation_change_0099",
    "trg_zone_shelf_evidence_lineage_0099",
    "trg_shelf_shelf_evidence_lineage_0099",
)
FUNCTIONS_0099 = (
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


def _count_named_objects(engine, catalog: str, names: tuple[str, ...]) -> int:
    if catalog == "pg_trigger":
        query = text(
            "SELECT COUNT(*) FROM pg_trigger "
            "WHERE NOT tgisinternal AND tgname = ANY(:names)"
        )
    elif catalog == "pg_proc":
        query = text(
            "SELECT COUNT(*) FROM pg_proc "
            "WHERE pg_function_is_visible(oid) AND proname = ANY(:names)"
        )
    else:
        raise ValueError(f"Unsupported PostgreSQL catalog: {catalog}")
    with engine.connect() as connection:
        return connection.execute(query, {"names": list(names)}).scalar_one()


def _assert_0099_present(engine) -> None:
    assert _count_named_objects(engine, "pg_trigger", TRIGGERS_0099) == len(TRIGGERS_0099)
    assert _count_named_objects(engine, "pg_proc", FUNCTIONS_0099) == len(FUNCTIONS_0099)


def _assert_0100_present(engine, *, expected: bool) -> None:
    trigger_count = _count_named_objects(engine, "pg_trigger", (TRIGGER_0100,))
    function_count = _count_named_objects(engine, "pg_proc", (FUNCTION_0100,))
    expected_count = 1 if expected else 0
    assert trigger_count == expected_count, (
        f"expected {expected_count} migration 0100 triggers, got {trigger_count}"
    )
    assert function_count == expected_count, (
        f"expected {expected_count} migration 0100 functions, got {function_count}"
    )


def main() -> None:
    configured_url = os.environ.get("DATABASE_URL")
    if not configured_url:
        raise RuntimeError("DATABASE_URL is required")
    base_url = make_url(configured_url)
    if base_url.get_backend_name() != "postgresql":
        raise RuntimeError("this smoke requires PostgreSQL")

    database_name = f"smart_shelf_0100_cycle_{uuid4().hex[:8]}"
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
        _assert_0099_present(target_engine)
        _assert_0100_present(target_engine, expected=True)

        command.downgrade(config, DOWN_REVISION)
        _assert_revision(target_engine, DOWN_REVISION)
        _assert_0099_present(target_engine)
        _assert_0100_present(target_engine, expected=False)

        command.upgrade(config, UP_REVISION)
        _assert_revision(target_engine, UP_REVISION)
        _assert_0099_present(target_engine)
        _assert_0100_present(target_engine, expected=True)

        print(
            "PostgreSQL 0100 migration-cycle smoke passed: isolated database "
            "upgraded to 0100, downgraded to 0099 with only the 0100 trigger "
            "and function removed, then re-applied 0100 successfully; all "
            "0099 guards remained present throughout."
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
