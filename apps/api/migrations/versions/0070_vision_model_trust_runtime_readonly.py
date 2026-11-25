"""Restrict ONNX model trust-state writes to the migration/deployment principal."""
from __future__ import annotations

import os
import re

import sqlalchemy as sa
from alembic import op


revision = "0070_vision_model_trust_runtime_readonly"
down_revision = "0069_vision_model_release_trust_state"
branch_labels = None
depends_on = None

_RUNTIME_ROLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_TRUST_TABLES = ("vision_model_release_states", "vision_model_release_events")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    app_env = os.getenv("APP_ENV", "development").strip().lower()
    runtime_role = os.getenv("APP_DB_USER", "").strip()
    if not runtime_role:
        if app_env == "production":
            raise RuntimeError("APP_DB_USER is required for production trust-state privilege isolation")
        return
    if not _RUNTIME_ROLE.fullmatch(runtime_role):
        raise RuntimeError("APP_DB_USER is not a safe PostgreSQL role identifier")

    current_user = bind.execute(sa.text("SELECT current_user")).scalar_one()
    if runtime_role == current_user:
        raise RuntimeError("APP_DB_USER must differ from the migration owner")

    role_exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role_name"),
        {"role_name": runtime_role},
    ).scalar_one_or_none()
    if role_exists is None:
        if app_env == "production":
            raise RuntimeError("Configured APP_DB_USER does not exist; refusing production migration")
        return

    trust_owner = bind.execute(
        sa.text(
            """
            SELECT pg_get_userbyid(relowner)
            FROM pg_class
            WHERE oid = 'public.vision_model_release_states'::regclass
            """
        )
    ).scalar_one()
    if trust_owner == runtime_role:
        raise RuntimeError("APP_DB_USER must not own ONNX model trust-state tables")

    quoted_role = bind.dialect.identifier_preparer.quote(runtime_role)
    for table_name in _TRUST_TABLES:
        op.execute(
            f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.{table_name} FROM {quoted_role}"
        )
        op.execute(f"GRANT SELECT ON TABLE public.{table_name} TO {quoted_role}")

    sequence = bind.execute(
        sa.text(
            """
            SELECT namespace.nspname, relation.relname
            FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE relation.oid = to_regclass(
                pg_get_serial_sequence('public.vision_model_release_events', 'id')
            )
            """
        )
    ).one_or_none()
    if sequence is not None:
        quoted_schema = bind.dialect.identifier_preparer.quote(sequence.nspname)
        quoted_sequence = bind.dialect.identifier_preparer.quote(sequence.relname)
        op.execute(
            f"REVOKE ALL ON SEQUENCE {quoted_schema}.{quoted_sequence} FROM {quoted_role}"
        )


def downgrade() -> None:
    # Deliberately do not restore runtime write privileges on trust-state tables.
    return
