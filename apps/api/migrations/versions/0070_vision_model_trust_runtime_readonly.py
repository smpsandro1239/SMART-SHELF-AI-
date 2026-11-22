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

    runtime_role = os.getenv("APP_DB_USER", "").strip()
    if not runtime_role:
        return
    if not _RUNTIME_ROLE.fullmatch(runtime_role):
        raise RuntimeError("APP_DB_USER is not a safe PostgreSQL role identifier")

    role_exists = bind.execute(
        sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role_name"),
        {"role_name": runtime_role},
    ).scalar_one_or_none()
    if role_exists is None:
        return

    quoted_role = bind.dialect.identifier_preparer.quote(runtime_role)
    for table_name in _TRUST_TABLES:
        op.execute(
            f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.{table_name} FROM {quoted_role}"
        )
        op.execute(f"GRANT SELECT ON TABLE public.{table_name} TO {quoted_role}")

    sequence_revoke = bind.execute(
        sa.text(
            """
            SELECT format(
                'REVOKE ALL ON SEQUENCE %s FROM %I',
                pg_get_serial_sequence('public.vision_model_release_events', 'id'),
                :role_name
            )
            WHERE pg_get_serial_sequence('public.vision_model_release_events', 'id') IS NOT NULL
            """
        ),
        {"role_name": runtime_role},
    ).scalar_one_or_none()
    if sequence_revoke:
        op.execute(sequence_revoke)


def downgrade() -> None:
    # Deliberately do not restore runtime write privileges on trust-state tables.
    return
