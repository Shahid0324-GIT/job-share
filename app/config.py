from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./jobshare.db"
    admin_password: str = "change-me"
    secret_key: str = "change-me-in-production"
    environment: str = "development"
    max_fetch_bytes: int = 1_000_000

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def require_production_secrets(self):
        if self.environment.lower() == "production" and (self.admin_password == "change-me" or self.secret_key == "change-me-in-production"):
            raise ValueError("ADMIN_PASSWORD and SECRET_KEY must be configured in production.")
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.environment.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
