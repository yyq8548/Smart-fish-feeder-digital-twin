from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/fish_feeder.db"
    device_api_key: str = "change-me-in-production"
    cors_origins: str = "http://localhost:8080,http://127.0.0.1:8080"
    offline_after_seconds: int = 15

    model_config = SettingsConfigDict(env_file=".env", env_prefix="FISH_FEEDER_")

    @property
    def allowed_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
