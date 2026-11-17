import pytest
from pydantic import ValidationError

from app.config import Settings


def _clear_secret_environment(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    monkeypatch.delenv("BOOTSTRAP_ADMIN_KEY", raising=False)


def test_production_requires_unique_jwt_and_bootstrap_secrets(monkeypatch):
    _clear_secret_environment(monkeypatch)
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, app_env="production", bootstrap_admin_key="b" * 32)


def test_production_rejects_short_jwt_secret(monkeypatch):
    _clear_secret_environment(monkeypatch)
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key="x" * 31,
            bootstrap_admin_key="b" * 32,
        )


def test_production_rejects_short_bootstrap_secret(monkeypatch):
    _clear_secret_environment(monkeypatch)
    with pytest.raises(ValidationError, match="BOOTSTRAP_ADMIN_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key="j" * 32,
            bootstrap_admin_key="b" * 31,
        )


@pytest.mark.parametrize("secret", [
    "replace_with_a_long_random_secret",
    "test-only-secret-not-for-production",
    "example-secret-value-that-is-long-enough",
])
def test_production_rejects_placeholder_jwt_secrets(monkeypatch, secret):
    _clear_secret_environment(monkeypatch)
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key=secret,
            bootstrap_admin_key="b" * 32,
        )


@pytest.mark.parametrize("secret", [
    "replace_with_a_separate_random_secret",
    "placeholder-bootstrap-secret-value-long",
])
def test_production_rejects_placeholder_bootstrap_secrets(monkeypatch, secret):
    _clear_secret_environment(monkeypatch)
    with pytest.raises(ValidationError, match="BOOTSTRAP_ADMIN_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key="j" * 32,
            bootstrap_admin_key=secret,
        )


@pytest.mark.parametrize("secret", [" " * 40, "j" * 20 + " " * 12])
def test_production_rejects_whitespace_in_jwt_secret(monkeypatch, secret):
    _clear_secret_environment(monkeypatch)
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key=secret,
            bootstrap_admin_key="b" * 32,
        )


@pytest.mark.parametrize("secret", [" " * 40, "b" * 20 + " " * 12])
def test_production_rejects_whitespace_in_bootstrap_secret(monkeypatch, secret):
    _clear_secret_environment(monkeypatch)
    with pytest.raises(ValidationError, match="BOOTSTRAP_ADMIN_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key="j" * 32,
            bootstrap_admin_key=secret,
        )


def test_production_rejects_reused_secrets(monkeypatch):
    _clear_secret_environment(monkeypatch)
    shared_secret = "s" * 40
    with pytest.raises(ValidationError, match="must be different"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key=shared_secret,
            bootstrap_admin_key=shared_secret,
        )


def test_production_accepts_separate_strong_secrets(monkeypatch):
    _clear_secret_environment(monkeypatch)
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key="j" * 32,
        bootstrap_admin_key="b" * 32,
    )

    assert settings.app_env == "production"
    assert settings.jwt_secret_key != settings.bootstrap_admin_key


def test_development_keeps_local_defaults_available(monkeypatch):
    _clear_secret_environment(monkeypatch)
    settings = Settings(_env_file=None, app_env="development")

    assert settings.jwt_secret_key == "INSECURE-DEVELOPMENT-KEY-CHANGE-ME"
