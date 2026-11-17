import pytest
from pydantic import ValidationError

from app.config import Settings


def test_production_requires_unique_jwt_and_bootstrap_secrets():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(_env_file=None, app_env="production")


def test_production_rejects_short_jwt_secret():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key="x" * 31,
            bootstrap_admin_key="b" * 32,
        )


def test_production_rejects_short_bootstrap_secret():
    with pytest.raises(ValidationError, match="BOOTSTRAP_ADMIN_KEY"):
        Settings(
            _env_file=None,
            app_env="production",
            jwt_secret_key="j" * 32,
            bootstrap_admin_key="b" * 31,
        )


def test_production_accepts_separate_strong_secrets():
    settings = Settings(
        _env_file=None,
        app_env="production",
        jwt_secret_key="j" * 32,
        bootstrap_admin_key="b" * 32,
    )

    assert settings.app_env == "production"
    assert settings.jwt_secret_key != settings.bootstrap_admin_key


def test_development_keeps_local_defaults_available():
    settings = Settings(_env_file=None, app_env="development")

    assert settings.jwt_secret_key == "INSECURE-DEVELOPMENT-KEY-CHANGE-ME"
