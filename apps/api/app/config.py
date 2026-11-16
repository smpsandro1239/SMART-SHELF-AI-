from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "SMART SHELF AI API"
    app_env: str = "development"
    database_url: str = "sqlite:///./smart_shelf_dev.db"
    jwt_secret_key: str = "INSECURE-DEVELOPMENT-KEY-CHANGE-ME"
    jwt_access_token_minutes: int = Field(default=30, ge=1, le=1440)
    bootstrap_admin_key: str = ""
    cors_allowed_origins: str = "http://localhost:5173"
    image_storage_path: str = "./storage/shelf-images"
    max_image_upload_bytes: int = Field(default=10485760, ge=1024, le=52428800)
    vision_provider_factory: str = ""
    ocr_provider_factory: str = ""
    ocr_provider_name: str = "paddleocr"
    ocr_model_version: str = "PP-OCRv5-pt"
    vision_processing_timeout_seconds: int = Field(default=86400, ge=60, le=604800)
    product_matching_min_similarity: float = Field(default=0.90, ge=0.0, le=1.0)
    product_matching_min_margin: float = Field(default=0.05, ge=0.0, le=2.0)
    artifact_inventory_hmac_keys_json: str = ""
    # None means secure-by-default in production, compatibility in non-production.
    artifact_inventory_allow_legacy_ingestion: bool | None = None
    artifact_inventory_max_age_minutes: int = Field(default=15, ge=1, le=1440)

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
