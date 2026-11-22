"""Verify a PostgreSQL application role cannot mutate schema or bypass trust guards."""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError


def _assert_denied(connection, statement: str, label: str) -> None:
    try:
        connection.execute(text(statement))
        connection.commit()
    except DBAPIError:
        connection.rollback()
        return
    raise AssertionError(f"Runtime role unexpectedly succeeded at {label}")


def main() -> None:
    database_url = os.environ.get("RUNTIME_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("RUNTIME_DATABASE_URL is required for the runtime-role smoke test")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            role = connection.execute(text("""
                SELECT current_user, rol.rolsuper, rol.rolcreatedb, rol.rolcreaterole,
                       rol.rolreplication, rol.rolbypassrls
                FROM pg_roles AS rol
                WHERE rol.rolname = current_user
            """)).one()
            if any(role[index] for index in range(1, 6)):
                raise AssertionError(f"Runtime role has an elevated role attribute: {role}")

            memberships = connection.execute(text("""
                SELECT COUNT(*)
                FROM pg_auth_members
                WHERE member = (SELECT oid FROM pg_roles WHERE rolname = current_user)
            """)).scalar_one()
            if memberships:
                raise AssertionError("Runtime role unexpectedly inherits another PostgreSQL role")

            owned_objects = connection.execute(text("""
                SELECT
                    (SELECT COUNT(*) FROM pg_class
                     WHERE relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user))
                    + (SELECT COUNT(*) FROM pg_namespace
                       WHERE nspowner = (SELECT oid FROM pg_roles WHERE rolname = current_user))
                    + (SELECT COUNT(*) FROM pg_database
                       WHERE datdba = (SELECT oid FROM pg_roles WHERE rolname = current_user))
            """)).scalar_one()
            if owned_objects:
                raise AssertionError(f"Runtime role owns {owned_objects} database objects")

            if connection.execute(text(
                "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
            )).scalar_one():
                raise AssertionError("Runtime role can CREATE objects in public schema")

            protected_tables = ("vision_model_release_states", "vision_model_release_events")
            for table in protected_tables:
                if not connection.execute(text(
                    "SELECT has_table_privilege(current_user, :table_name, 'SELECT')"
                ), {"table_name": table}).scalar_one():
                    raise AssertionError(f"Runtime role cannot read protected trust table {table}")

                for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                    allowed = connection.execute(text(
                        "SELECT has_table_privilege(current_user, :table_name, :privilege)"
                    ), {"table_name": table, "privilege": privilege}).scalar_one()
                    if allowed:
                        raise AssertionError(
                            f"Runtime role unexpectedly has {privilege} on protected trust table {table}"
                        )

            sequence_name = connection.execute(text(
                "SELECT pg_get_serial_sequence('vision_model_release_events', 'id')"
            )).scalar_one()
            if sequence_name and any(
                connection.execute(text(
                    "SELECT has_sequence_privilege(current_user, :sequence_name, :privilege)"
                ), {"sequence_name": sequence_name, "privilege": privilege}).scalar_one()
                for privilege in ("USAGE", "SELECT", "UPDATE")
            ):
                raise AssertionError("Runtime role unexpectedly has privileges on the trust-event sequence")

            denied_statements = (
                ("INSERT INTO vision_model_release_states "
                 "(deployment_id, model_id, highest_release_version, manifest_sha256, key_id, "
                 "detector_sha256, embedding_sha256, updated_at) "
                 "SELECT 'runtime-probe', 'shelf-detector', 1, repeat('a', 64), 'runtime', "
                 "repeat('b', 64), NULL, CURRENT_TIMESTAMP WHERE FALSE", "INSERT trust state"),
                ("UPDATE vision_model_release_states SET highest_release_version = "
                 "highest_release_version + 1 WHERE FALSE", "UPDATE trust state"),
                ("DELETE FROM vision_model_release_states WHERE FALSE", "DELETE trust state"),
                ("INSERT INTO vision_model_release_events "
                 "(deployment_id, model_id, release_version, manifest_sha256, key_id, decision, reason, created_at) "
                 "SELECT 'runtime-probe', 'shelf-detector', 1, repeat('a', 64), 'runtime', "
                 "'ACCEPTED', 'probe', CURRENT_TIMESTAMP WHERE FALSE", "INSERT trust event"),
                ("UPDATE vision_model_release_events SET reason = 'tampered' WHERE FALSE", "UPDATE trust event"),
                ("DELETE FROM vision_model_release_events WHERE FALSE", "DELETE trust event"),
                ("TRUNCATE vision_model_release_states, vision_model_release_events", "TRUNCATE trust tables"),
            )
            for statement, label in denied_statements:
                _assert_denied(connection, statement, label)

            _assert_denied(
                connection,
                "CREATE TABLE public.runtime_role_forbidden_probe (id integer)",
                "CREATE TABLE",
            )
            _assert_denied(
                connection,
                "ALTER TABLE vision_model_release_states ADD COLUMN runtime_probe integer",
                "ALTER TABLE",
            )
            _assert_denied(
                connection,
                "TRUNCATE TABLE vision_model_release_states",
                "TRUNCATE",
            )
    finally:
        engine.dispose()

    print("PostgreSQL runtime-role smoke passed: least privilege, operational DML, read-only model trust state and no memberships/ownership.")


if __name__ == "__main__":
    main()
