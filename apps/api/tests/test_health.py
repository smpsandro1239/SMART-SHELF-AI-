import os

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite:///./test_unused.db"

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.main import app
import app.main as main_module

client = TestClient(app)


def _client_with_database(engine):
    previous_overrides = app.dependency_overrides.copy()

    def override_get_db():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[main_module.get_db] = override_get_db
    return TestClient(app), previous_overrides


def _restore_dependency_overrides(previous_overrides):
    app.dependency_overrides.clear()
    app.dependency_overrides.update(previous_overrides)


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_readiness_rejects_database_without_alembic_migrations(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(main_module, "_expected_alembic_heads", lambda: {"release-head"})
    test_client, previous_overrides = _client_with_database(engine)
    try:
        response = test_client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["detail"] == "Database migrations are not up to date"
    finally:
        _restore_dependency_overrides(previous_overrides)
        engine.dispose()


def test_readiness_rejects_database_on_an_older_migration_head(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(128) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('old-head')"))
    monkeypatch.setattr(main_module, "_expected_alembic_heads", lambda: {"release-head"})
    test_client = _client_with_database(engine)
    try:
        response = test_client.get("/health/ready")
        assert response.status_code == 503
        assert response.json()["detail"] == "Database migrations are not up to date"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_readiness_accepts_database_at_all_current_migration_heads(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(128) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version (version_num) VALUES ('release-head')"))
    monkeypatch.setattr(main_module, "_expected_alembic_heads", lambda: {"release-head"})
    test_client = _client_with_database(engine)
    try:
        response = test_client.get("/health/ready")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ready",
            "database": "connected",
            "migrations": "current",
        }
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
