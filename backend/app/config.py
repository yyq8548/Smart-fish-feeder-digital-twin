from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./fish_feeder.db"
    device_api_key: str = "local-development-key"
    bootstrap_device_uid: str = "feeder-001"
    credential_pepper: str = "change-this-credential-pepper"
    admin_username: str = "admin"
    admin_password: str = "change-this-admin-password"
    jwt_secret: str = "change-this-jwt-secret-at-least-32-characters"
    jwt_expire_minutes: int = 30
    cors_origins: str = "http://localhost:8080,http://127.0.0.1:8080"
    offline_after_seconds: int = 15
    max_telemetry_age_seconds: int = 86_400
    max_future_skew_seconds: int = 300
    telemetry_rate_limit_per_minute: int = Field(default=120, ge=1)
    login_rate_limit_per_minute: int = Field(default=10, ge=1)
    reliability_scan_interval_seconds: int = Field(default=60, ge=5)
    command_lease_seconds: int = Field(default=30, ge=5, le=300)
    credential_attempt_rate_limit_per_minute: int = Field(default=30, ge=1)

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FISH_FEEDER_")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
