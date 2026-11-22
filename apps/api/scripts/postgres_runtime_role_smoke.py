"""Verify PostgreSQL runtime identity, grants and model-trust isolation."""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.vision_model_release import assert_model_release_current


_PROTECTED_TABLES = ("vision_model_release_states", "vision_model_release_events")
_OPERATIONAL_TABLE_PRIVILEGES = frozenset({"SELECT", "INSERT", "UPDATE", "DELETE"})
_OPERATIONAL_SEQUENCE_PRIVILEGES = frozenset({"USAGE", "SELECT", "UPDATE"})


def _assert_denied(connection, statement: str, label: str) -> None:
    try:
        connection.execute(text(statement))
        connection.commit()
    except DBAPIError:
        connection.rollback()
        return
    raise AssertionError(f"Runtime role unexpectedly succeeded at {label}")


def _assert_default_privileges(connection) -> None:
    rows = connection.execute(text("""
        SELECT defaults.defaclobjtype, privilege.privilege_type, privilege.is_grantable
        FROM pg_default_acl AS defaults
        CROSS JOIN LATERAL aclexplode(defaults.defaclacl) AS privilege
        WHERE defaults.defaclnamespace = 'public'::regnamespace
          AND privilege.grantee = (
              SELECT oid FROM pg_roles WHERE rolname = current_user
          )
    """)).all()

    actual: dict[str, set[str]] = {"r": set(), "S": set()}
    for object_type, privilege, grantable in rows:
        if object_type not in actual:
            continue
        if grantable:
            raise AssertionError(
                f"Runtime default privilege {privilege} for object type {object_type} is grantable"
            )
        actual[object_type].add(privilege)

    expected = {
        "r": _OPERATIONAL_TABLE_PRIVILEGES,
        "S": _OPERATIONAL_SEQUENCE_PRIVILEGES,
    }
    for object_type, required in expected.items():
        if not required.issubset(actual[object_type]):
            missing = sorted(required - actual[object_type])
            raise AssertionError(
                f"Runtime role is missing future-object privileges {missing} for type {object_type}"
            )
        unexpected = actual[object_type] - required
        if unexpected:
            raise AssertionError(
                f"Runtime role has unexpected future-object privileges "
                f"{sorted(unexpected)} for type {object_type}"
            )


def main() -> None:
    database_url = os.environ.get("RUNTIME_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("RUNTIME_DATABASE_URL is required for the runtime-role smoke test")

    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        probe_deployment = os.getenv("TRUST_PROBE_DEPLOYMENT_ID", "").strip()
        if probe_deployment:
            session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
            with session_factory() as db:
                assert_model_release_current(
                    db,
                    deployment_id=probe_deployment,
                    model_release={
                        "model_id": "shelf-detector",
                        "release_version": 3,
                        "key_id": "release-smoke",
                        "manifest_sha256": f"{3:064x}",
                        "detector_sha256": "a" * 64,
                        "embedding_sha256": None,
                    },
                )
                db.rollback()

        with engine.connect() as connection:
            role = connection.execute(text("""
                SELECT current_user, rol.rolcanlogin, rol.rolsuper, rol.rolcreatedb,
                       rol.rolcreaterole, rol.rolreplication, rol.rolbypassrls, rol.rolinherit
                FROM pg_roles AS rol
                WHERE rol.rolname = current_user
            """)).one()
            if not role[1] or any(role[index] for index in range(2, 7)) or role[7]:
                raise AssertionError(f"Runtime role has unexpected login/elevated/inheritance attributes: {role}")

            memberships = connection.execute(text("""
                SELECT COUNT(*)
                FROM pg_auth_members
                WHERE member = (SELECT oid FROM pg_roles WHERE rolname = current_user)
            """)).scalar_one()
            if memberships:
                raise AssertionError("Runtime role unexpectedly inherits another PostgreSQL role")

            owned_objects = connection.execute(text("""
                SELECT COUNT(*)
                FROM pg_shdepend
                WHERE refclassid = 'pg_authid'::regclass
                  AND refobjid = (SELECT oid FROM pg_roles WHERE rolname = current_user)
                  AND deptype = 'o'
            """)).scalar_one()
            if owned_objects:
                raise AssertionError(f"Runtime role owns {owned_objects} PostgreSQL objects")

            if not connection.execute(text(
                "SELECT has_database_privilege(current_user, current_database(), 'CONNECT')"
            )).scalar_one():
                raise AssertionError("Runtime role cannot CONNECT to the application database")

            if not connection.execute(text(
                "SELECT has_schema_privilege(current_user, 'public', 'USAGE')"
            )).scalar_one():
                raise AssertionError("Runtime role cannot use the public schema")

            if connection.execute(text(
                "SELECT has_schema_privilege(current_user, 'public', 'CREATE')"
            )).scalar_one():
                raise AssertionError("Runtime role can CREATE objects in public schema")

            _assert_default_privileges(connection)

            for table in _PROTECTED_TABLES:
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

    print(
        "PostgreSQL runtime-role smoke passed: LOGIN/NOSUPERUSER/NOINHERIT, "
        "no memberships or ownership, operational future-object ACLs, "
        "database/schema access and read-only model trust state."
    )


if __name__ == "__main__":
    main()
