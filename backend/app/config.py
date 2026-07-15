from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./fish_feeder.db"
    device_api_key: str = "local-development-key"
    bootstrap_device_uid: str = "feeder-001"
    credential_pepper: str = "change-this-credential-pepper"
    admin_username: str = "admin"
    admin_password: str = "change-this-admin-password"
    demo_enabled: bool = True
    demo_username: str = Field(default="demo", min_length=3, max_length=80)
    demo_password: str = Field(default="smartfishdemo", min_length=8, max_length=128)
    demo_device_uid: str = Field(default="demo-feeder-001", min_length=3, max_length=80)
    jwt_secret: str = "change-this-jwt-secret-at-least-32-characters"
    jwt_expire_minutes: int = 30
    email_verification_expire_minutes: int = Field(default=1_440, ge=15, le=10_080)
    password_reset_expire_minutes: int = Field(default=30, ge=5, le=1_440)
    public_app_url: str = "http://localhost:8080"
    email_delivery_mode: Literal["console", "smtp"] = "console"
    smtp_host: str = ""
    smtp_port: int = Field(default=587, ge=1, le=65_535)
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_starttls: bool = True
    root_path: str = ""
    cors_origins: str = "http://localhost:8080,http://127.0.0.1:8080"
    offline_after_seconds: int = 15
    max_telemetry_age_seconds: int = 86_400
    max_future_skew_seconds: int = 300
    telemetry_rate_limit_per_minute: int = Field(default=120, ge=1)
    login_rate_limit_per_minute: int = Field(default=10, ge=1)
    demo_login_rate_limit_per_minute: int = Field(default=60, ge=1)
    reliability_scan_interval_seconds: int = Field(default=60, ge=5)
    command_lease_seconds: int = Field(default=30, ge=5, le=300)
    command_result_grace_seconds: int = Field(default=90, ge=15, le=600)
    manual_command_ttl_seconds: int = Field(default=45, ge=5, le=300)
    require_online_for_actuation: bool = True
    credential_attempt_rate_limit_per_minute: int = Field(default=30, ge=1)
    registration_rate_limit_per_minute: int = Field(default=5, ge=1)
    password_reset_rate_limit_per_minute: int = Field(default=5, ge=1)
    pairing_rate_limit_per_minute: int = Field(default=10, ge=1)

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FISH_FEEDER_")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
