from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SMART SHELF AI API"
    app_env: str = "development"
    database_url: str = "sqlite:///./smart_shelf_dev.db"
    jwt_secret_key: str = "INSECURE-DEVELOPMENT-KEY-CHANGE-ME"
    jwt_access_token_minutes: int = Field(default=30, ge=1, le=1440)
    bootstrap_admin_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @model_validator(mode="after")
    def validate_production_secrets(self):
        if self.app_env.lower() == "production":
            if self.jwt_secret_key == "INSECURE-DEVELOPMENT-KEY-CHANGE-ME" or len(self.jwt_secret_key) < 32:
                raise ValueError("Production requires a unique JWT_SECRET_KEY with at least 32 characters")
            if len(self.bootstrap_admin_key) < 32:
                raise ValueError("Production requires a unique BOOTSTRAP_ADMIN_KEY with at least 32 characters")
        return self


settings = Settings()
