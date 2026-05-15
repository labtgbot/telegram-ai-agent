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

    app_name: str = Field(default="telegram-ai-agent-backend")
    app_env: str = Field(default="development")
    app_debug: bool = Field(default=False)
    log_level: str = Field(default="INFO")
    log_format: str = Field(
        default="json",
        description="Log format: 'json' for production, 'console' for dev.",
    )

    api_v1_prefix: str = Field(default="/api/v1")

    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_ai_agent",
        description="SQLAlchemy URL with async driver (asyncpg).",
    )

    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL.",
    )

    health_check_timeout: float = Field(
        default=2.0,
        description="Per-dependency timeout (seconds) for /health checks.",
    )

    @property
    def sync_database_url(self) -> str:
        """Alembic offline mode wants a sync-compatible URL."""
        return self.database_url.replace("+asyncpg", "+psycopg")

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "local"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
