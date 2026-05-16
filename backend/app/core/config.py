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
        description="Telegram bot token; used for WebApp initData HMAC + Bot API calls.",
    )
    telegram_bot_username: str = Field(
        default="",
        description="Bot username (without @); embedded in referral links.",
    )
    telegram_api_base_url: str = Field(
        default="https://api.telegram.org",
        description="Telegram Bot API base URL (override for tests or self-hosted gateways).",
    )
    telegram_init_data_max_age: int = Field(
        default=86400,
        description="Maximum age (seconds) of WebApp initData accepted by the API.",
    )
    telegram_webhook_secret: str = Field(
        default="",
        description=(
            "Secret value Telegram sends as 'X-Telegram-Bot-Api-Secret-Token'. "
            "Empty disables verification (useful for local dev)."
        ),
    )
    telegram_mini_app_url: str = Field(
        default="",
        description="HTTPS URL of the Mini App opened from inline keyboards.",
    )
    telegram_signup_bonus_tokens: int = Field(
        default=50,
        description="Tokens credited to every newly registered Telegram user.",
    )
    telegram_referral_bonus_tokens: int = Field(
        default=100,
        description=(
            "Tokens credited to a referrer when the user they invited "
            "completes their first purchase."
        ),
    )
    daily_bonus_enabled: bool = Field(
        default=True,
        description="Master switch for the daily-bonus retention loop.",
    )
    daily_bonus_amounts: str = Field(
        default="10,12,15,20",
        description=(
            "Comma-separated ladder of daily-bonus amounts indexed by streak "
            "day (1, 2, 3, …).  The last value is reused for every "
            "subsequent consecutive day, so the default caps at 20 tokens."
        ),
    )
    telegram_set_commands_on_startup: bool = Field(
        default=True,
        description="Call setMyCommands when the FastAPI app starts (skipped without token).",
    )

    composio_api_key: str = Field(
        default="",
        description="Composio API key — when empty the mock client is used.",
    )
    composio_default_user_id: str = Field(
        default="",
        description="Default Composio user/connected-account identifier used for tool calls.",
    )
    composio_base_url: str = Field(
        default="https://backend.composio.dev",
        description="Composio MCP API base URL.",
    )
    composio_timeout_seconds: float = Field(
        default=30.0,
        description="Per-request HTTP timeout for Composio tool invocations.",
    )
    composio_max_retries: int = Field(
        default=3,
        description="Maximum attempts (including the first call) for transient failures.",
    )
    composio_backoff_base_seconds: float = Field(
        default=0.5,
        description="Base delay for exponential backoff between retries (seconds).",
    )
    composio_backoff_max_seconds: float = Field(
        default=8.0,
        description="Upper bound for a single backoff delay.",
    )
    composio_default_toolkits: str = Field(
        default="gemini,composio_search,image_gen,video_gen",
        description="Comma-separated list of toolkits the client surfaces by default.",
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
    def composio_enabled(self) -> bool:
        """Whether to use the real Composio client (vs. mock)."""
        return bool(self.composio_api_key and self.composio_api_key.strip())

    @property
    def composio_toolkits(self) -> tuple[str, ...]:
        """Parse ``composio_default_toolkits`` into a normalised tuple."""
        raw = (self.composio_default_toolkits or "").strip()
        if not raw:
            return ()
        return tuple(chunk.strip() for chunk in raw.split(",") if chunk.strip())

    @property
    def daily_bonus_ladder(self) -> tuple[int, ...]:
        """Parse :attr:`daily_bonus_amounts` into a tuple of positive ints.

        Empty / malformed values fall back to ``(10,)`` so the loop is
        always operational; misconfiguration in production logs a
        warning at service-load time (see ``daily_bonus.py``).
        """
        raw = (self.daily_bonus_amounts or "").strip()
        out: list[int] = []
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                value = int(chunk)
            except ValueError:
                continue
            if value > 0:
                out.append(value)
        return tuple(out) if out else (10,)

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
