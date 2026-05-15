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

    telegram_bot_token: str = Field(
        default="",
        description="Telegram bot token; used to verify WebApp initData HMAC.",
    )
    telegram_init_data_max_age: int = Field(
        default=86400,
        description="Maximum age (seconds) of WebApp initData accepted by the API.",
    )

    admin_jwt_secret: str = Field(
        default="change-me",
        description="HS256 secret used to sign admin JWT tokens.",
    )
    admin_jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm.",
    )
    admin_access_token_ttl: int = Field(
        default=15 * 60,
        description="Admin access-token lifetime (seconds).",
    )
    admin_refresh_token_ttl: int = Field(
        default=7 * 24 * 60 * 60,
        description="Admin refresh-token lifetime (seconds).",
    )
    admin_login_code_ttl: int = Field(
        default=5 * 60,
        description="One-time admin login code lifetime (seconds).",
    )
    admin_login_code_length: int = Field(
        default=6,
        description="Decimal length of the one-time admin login code.",
    )
    admin_login_max_attempts: int = Field(
        default=5,
        description="Maximum number of code verification attempts per login session.",
    )
    admin_super_telegram_ids: str = Field(
        default="",
        description="Comma-separated Telegram IDs that get the super_admin role.",
    )
    totp_issuer: str = Field(
        default="Telegram AI Agent",
        description="Issuer label shown in TOTP-compatible apps.",
    )

    @property
    def sync_database_url(self) -> str:
        """Alembic offline mode wants a sync-compatible URL."""
        return self.database_url.replace("+asyncpg", "+psycopg")

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "local"}

    @property
    def super_admin_ids(self) -> set[int]:
        """Parse ``admin_super_telegram_ids`` into a set of Telegram IDs."""
        raw = (self.admin_super_telegram_ids or "").strip()
        if not raw:
            return set()
        out: set[int] = set()
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                out.add(int(chunk))
            except ValueError:
                continue
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
