from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./jobshare.db"
    admin_password: str = "change-me"
    secret_key: str = "change-me-in-production"
    environment: str = "development"
    max_fetch_bytes: int = 1_000_000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def secure_cookies(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
