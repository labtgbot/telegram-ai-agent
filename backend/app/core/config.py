"""Application settings loaded from environment variables.

Keep this module side-effect free: no I/O, no logger config — just declarative settings.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = Field(default="development")
    app_debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_ai_agent",
        description="SQLAlchemy URL with async driver (asyncpg).",
    )

    @property
    def sync_database_url(self) -> str:
        """Alembic offline mode wants a sync-compatible URL."""
        return self.database_url.replace("+asyncpg", "+psycopg")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
