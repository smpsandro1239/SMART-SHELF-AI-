#!/usr/bin/env bash
# Idempotently reconcile a least-privilege application role before migrations.
set -Eeuo pipefail

: "${POSTGRES_USER:?POSTGRES_USER must identify the migration/database owner}"
: "${POSTGRES_DB:?POSTGRES_DB must be set}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"
export PGPASSWORD="$POSTGRES_PASSWORD"
: "${APP_DB_USER:?APP_DB_USER must identify the runtime role}"
: "${APP_DB_PASSWORD:?APP_DB_PASSWORD must be a non-empty runtime password}"

if [[ "$APP_DB_USER" == "$POSTGRES_USER" ]]; then
  echo "APP_DB_USER must differ from POSTGRES_USER; runtime must not use the migration owner." >&2
  exit 1
fi

if [[ ! "$APP_DB_USER" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]]; then
  echo "APP_DB_USER must be a 1-63 character PostgreSQL identifier using ASCII letters, digits and underscores." >&2
  exit 1
fi

if [[ "${APP_ENV:-development}" == "production" ]]; then
  if [[ ${#APP_DB_PASSWORD} -lt 32 || ! "$APP_DB_PASSWORD" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "Production APP_DB_PASSWORD must contain at least 32 URL-safe characters." >&2
    exit 1
  fi
  if [[ ${#POSTGRES_PASSWORD} -lt 32 || ! "$POSTGRES_PASSWORD" =~ ^[A-Za-z0-9_-]+$ ]]; then
    echo "Production POSTGRES_PASSWORD must contain at least 32 URL-safe characters." >&2
    exit 1
  fi
fi

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 \
  --set=runtime_user="$APP_DB_USER" \
  --set=runtime_password="$APP_DB_PASSWORD" \
  --set=migration_user="$POSTGRES_USER" \
  --set=database_name="$POSTGRES_DB" <<'SQL'
BEGIN;

SELECT format(
    'CREATE ROLE %I LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT',
    :'runtime_user',
    :'runtime_password'
)
WHERE NOT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = :'runtime_user'
)
\gexec

SELECT format(
    'ALTER ROLE %I WITH LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS NOINHERIT',
    :'runtime_user',
    :'runtime_password'
)
\gexec

-- Strip inherited elevated roles and ownership/grants from any previously used role.
SELECT format('REVOKE %I FROM %I', granted_role.rolname, member_role.rolname)
FROM pg_auth_members AS membership
JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
JOIN pg_roles AS member_role ON member_role.oid = membership.member
WHERE member_role.rolname = :'runtime_user'
\gexec

REASSIGN OWNED BY :"runtime_user" TO :"migration_user";
DROP OWNED BY :"runtime_user";

GRANT CONNECT ON DATABASE :"database_name" TO :"runtime_user";
GRANT USAGE ON SCHEMA public TO :"runtime_user";
REVOKE CREATE ON SCHEMA public FROM :"runtime_user";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"runtime_user";
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO :"runtime_user";

-- Model-release trust state is readable by the application but writable only by
-- the migration/deployment principal. This also repairs grants on existing volumes.
SELECT format(
    'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON TABLE public.%I FROM %I',
    table_name,
    :'runtime_user'
)
FROM unnest(ARRAY['vision_model_release_states', 'vision_model_release_events']) AS protected(table_name)
WHERE to_regclass(format('public.%I', table_name)) IS NOT NULL
\gexec

SELECT format(
    'GRANT SELECT ON TABLE public.%I TO %I',
    table_name,
    :'runtime_user'
)
FROM unnest(ARRAY['vision_model_release_states', 'vision_model_release_events']) AS protected(table_name)
WHERE to_regclass(format('public.%I', table_name)) IS NOT NULL
\gexec

SELECT format(
    'REVOKE ALL ON SEQUENCE %s FROM %I',
    CASE
        WHEN to_regclass('public.vision_model_release_events') IS NOT NULL
        THEN pg_get_serial_sequence('public.vision_model_release_events', 'id')
        ELSE NULL
    END,
    :'runtime_user'
)
WHERE to_regclass('public.vision_model_release_events') IS NOT NULL
\gexec

ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_user" IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"runtime_user";
ALTER DEFAULT PRIVILEGES FOR ROLE :"migration_user" IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"runtime_user";

COMMIT;
SQL
