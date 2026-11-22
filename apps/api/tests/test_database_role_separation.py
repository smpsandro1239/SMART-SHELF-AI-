"""Deployment tests for PostgreSQL migration/runtime role separation."""
from pathlib import Path
import re
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[3]
COMPOSE = ROOT / "docker-compose.yml"
ROLE_BOOTSTRAP = ROOT / "infra" / "postgres" / "10-create-runtime-role.sh"


def _service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"(?ms)^  {re.escape(service)}:\n(?P<body>.*?)(?=^  [a-zA-Z0-9_-]+:\n|^volumes:)",
        compose,
    )
    assert match is not None, f"Missing Compose service: {service}"
    return match.group("body")


def test_migrations_use_owner_credentials_and_runtime_services_use_restricted_role():
    compose = COMPOSE.read_text(encoding="utf-8")
    migration = _service_block(compose, "migrate")
    api = _service_block(compose, "api")
    worker = _service_block(compose, "vision-worker")

    assert "alembic" in migration
    assert "POSTGRES_USER" in migration
    assert "POSTGRES_PASSWORD" in migration
    assert "APP_DB_USER" not in migration

    for service_name, block in (("api", api), ("vision-worker", worker)):
        assert "APP_DB_USER" in block, f"{service_name} must use the runtime role"
        assert "APP_DB_PASSWORD" in block, f"{service_name} must use the runtime secret"
        assert "POSTGRES_USER" not in block, f"{service_name} must not receive migration credentials"
        assert "POSTGRES_PASSWORD" not in block, f"{service_name} must not receive migration credentials"

    assert "migrate:" in api
    assert "service_completed_successfully" in api


def test_postgres_bootstrap_creates_non_owner_role_with_dml_only_grants():
    compose = COMPOSE.read_text(encoding="utf-8")
    bootstrap = ROLE_BOOTSTRAP.read_text(encoding="utf-8")

    db = _service_block(compose, "db")
    assert "10-create-runtime-role.sh:/docker-entrypoint-initdb.d/" in db
    assert "APP_DB_USER" in db
    assert "APP_DB_PASSWORD" in db

    assert '[[ "$APP_DB_USER" == "$POSTGRES_USER" ]]' in bootstrap
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in bootstrap
    assert "REVOKE CREATE ON SCHEMA public" in bootstrap
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" in bootstrap
    assert "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES" in bootstrap
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE" in bootstrap
    assert "REASSIGN OWNED BY" in bootstrap
    assert "DROP OWNED BY" in bootstrap
    assert "pg_auth_members" in bootstrap
    assert "GRANT CREATE" not in bootstrap
    assert "GRANT TRUNCATE" not in bootstrap


def test_api_no_longer_runs_alembic_with_runtime_database_credentials():
    compose = COMPOSE.read_text(encoding="utf-8")
    api = _service_block(compose, "api")

    assert "alembic" not in api
    assert '["uvicorn", "app.main:app"' in api


def test_runtime_role_bootstrap_has_valid_bash_syntax():
    bash = shutil.which("bash")
    assert bash is not None, "bash is required by the PostgreSQL container bootstrap"
    result = subprocess.run(
        [bash, "-n", str(ROLE_BOOTSTRAP)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
