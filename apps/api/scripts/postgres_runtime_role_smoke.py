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
                SELECT current_user, rol.super, rol.rolcreatedb, rol.rolcreaterole,
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

            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                allowed = connection.execute(text(
                    "SELECT has_table_privilege(current_user, 'vision_model_release_states', :privilege)"
                ), {"privilege": privilege}).scalar_one()
                if not allowed:
                    raise AssertionError(f"Runtime role is missing required {privilege} privilege")

            if connection.execute(text(
                "SELECT has_table_privilege(current_user, 'vision_model_release_states', 'TRUNCATE')"
            )).scalar_one():
                raise AssertionError("Runtime role unexpectedly has TRUNCATE privilege")

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

    print("PostgreSQL runtime-role smoke passed: least privilege, no memberships/ownership, DML only.")


if __name__ == "__main__":
    main()
