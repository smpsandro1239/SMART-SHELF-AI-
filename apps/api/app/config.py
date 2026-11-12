from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SMART SHELF AI API"
    app_env: str = "development"
    database_url: str = "sqlite:///./smart_shelf_dev.db"
    jwt_secret_key: str = "INSECURE-DEVELOPMENT-KEY-CHANGE-ME"
    jwt_access_token_minutes: int = 30
    bootstrap_admin_key: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
