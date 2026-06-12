"""Application settings loaded from environment variables.

Keep this module side-effect free: no I/O, no logger config — just declarative settings.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_ADMIN_JWT_SECRET = "change-me"  # noqa: S105 — sentinel, not a real secret
DEFAULT_APP_SECRET = "change-me"  # noqa: S105 — sentinel, not a real secret
NON_PRODUCTION_ENVS = frozenset({"development", "dev", "local", "test", "ci"})
COMPOSIO_MODE_REAL = "real"
COMPOSIO_MODE_MOCK = "mock"
COMPOSIO_MODES = frozenset({COMPOSIO_MODE_REAL, COMPOSIO_MODE_MOCK})


class InsecureDefaultSecretError(RuntimeError):
    """Raised when a placeholder secret leaks into a non-development env."""


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
    trusted_proxy_ips: str = Field(
        default="",
        description=(
            "Comma-separated IP/CIDR allowlist for peers whose X-Forwarded-For "
            "headers may be used to resolve the original client IP."
        ),
    )

    # ---------------------------------------------------------- DB pool tuning
    # See docs/PERFORMANCE.md "PostgreSQL connection pool" for sizing
    # guidance. Values target a single backend pod; multiply by the replica
    # count to get total open connections.
    db_pool_size: int = Field(
        default=20,
        description=(
            "Number of persistent connections kept open per worker. "
            "Total pool capacity is db_pool_size + db_max_overflow."
        ),
    )
    db_max_overflow: int = Field(
        default=10,
        description="Extra burst connections allowed above db_pool_size.",
    )
    db_pool_timeout: float = Field(
        default=10.0,
        description="Seconds a checkout waits for a free connection before raising.",
    )
    db_pool_recycle: int = Field(
        default=1800,
        description=(
            "Seconds before a pooled connection is recycled. Keeps the pool "
            "ahead of pgbouncer / cloud-provider idle-timeouts."
        ),
    )
    db_statement_cache_size: int = Field(
        default=1024,
        description="asyncpg per-connection statement cache size.",
    )

    # ----------------------------------------------------------- cache tuning
    balance_cache_ttl_seconds: int = Field(
        default=300,
        description=(
            "Soft TTL for the Redis-cached user balance. The cache is "
            "invalidated on every TokenService mutation, so this TTL only "
            "acts as a safety net for missed invalidations."
        ),
    )
    pricing_cache_ttl_seconds: int = Field(
        default=60,
        description=(
            "TTL for the in-process pricing config cache. Issue #36 sets the "
            "budget at 60 seconds so admin price changes propagate quickly "
            "while still absorbing the hottest read path."
        ),
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
    telegram_update_idempotency_ttl_seconds: int = Field(
        default=7 * 24 * 60 * 60,
        description=(
            "TTL for Redis keys that remember processed Telegram webhook update_id "
            "values. Keeps redeliveries from re-running non-idempotent bot handlers."
        ),
    )
    telegram_webhook_secret: str = Field(
        default="",
        description=(
            "Secret value Telegram sends as 'X-Telegram-Bot-Api-Secret-Token'. "
            "Empty disables verification only in local/dev/test environments."
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

    # ----------------------------------------------------------- age verification
    compliance_age_gate_enabled: bool = Field(
        default=False,
        description=(
            "Enables the age-verification endpoint stub. Off by default — turn "
            "on only when a feature gated on 18+ ships. See "
            "docs/legal/AGE_VERIFICATION.md."
        ),
    )
    compliance_age_gate_provider: str = Field(
        default="self_declared",
        description=(
            "Provider for age verification proofs. ``self_declared`` is "
            "development-only; production should use ``telegram_passport``, "
            "``veriff`` or ``yoti`` once integrated."
        ),
    )

    composio_mode: str = Field(
        default=COMPOSIO_MODE_REAL,
        description=(
            "Composio client mode: 'real' requires COMPOSIO_API_KEY; "
            "'mock' is only allowed in non-production environments."
        ),
    )
    composio_api_key: str = Field(
        default="",
        description="Composio API key required when COMPOSIO_MODE=real.",
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
        default=DEFAULT_ADMIN_JWT_SECRET,
        description=(
            "HS256 secret used to sign admin JWT tokens. The placeholder "
            "default is rejected at startup outside development — see "
            "Settings.assert_production_safe()."
        ),
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

    # ------------------------------------------------------------------ monitoring
    metrics_enabled: bool = Field(
        default=True,
        description="Expose Prometheus metrics at the configured metrics path.",
    )
    metrics_path: str = Field(
        default="/metrics",
        description="Path on the FastAPI app where Prometheus metrics are exposed.",
    )
    metrics_active_user_window_seconds: int = Field(
        default=300,
        description=(
            "Sliding window (seconds) used by the active-users gauge — a user "
            "is counted as active when they hit an instrumented endpoint within "
            "this window. 5-minute default matches Grafana 'now-5m' panels."
        ),
    )
    sentry_dsn: str = Field(
        default="",
        description="Sentry DSN — leave empty to disable Sentry initialisation.",
    )
    sentry_environment: str = Field(
        default="",
        description="Sentry environment tag; falls back to app_env when empty.",
    )
    sentry_traces_sample_rate: float = Field(
        default=0.1,
        description="Tracing sample rate for Sentry (0..1).",
    )
    sentry_profiles_sample_rate: float = Field(
        default=0.0,
        description="Profiling sample rate for Sentry (0..1); 0 disables profiling.",
    )
    sentry_release: str = Field(
        default="",
        description="Release tag forwarded to Sentry; defaults to the app version when empty.",
    )

    @property
    def sync_database_url(self) -> str:
        """Alembic offline mode wants a sync-compatible URL."""
        return self.database_url.replace("+asyncpg", "+psycopg")

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "local"}

    @property
    def is_non_production(self) -> bool:
        return self.app_env.lower() in NON_PRODUCTION_ENVS

    @property
    def composio_mode_normalized(self) -> str:
        return (self.composio_mode or "").strip().lower()

    @property
    def composio_mock_enabled(self) -> bool:
        return self.composio_mode_normalized == COMPOSIO_MODE_MOCK

    @property
    def composio_enabled(self) -> bool:
        """Whether to use the real Composio client."""
        return self.composio_mode_normalized == COMPOSIO_MODE_REAL and bool(
            self.composio_api_key and self.composio_api_key.strip()
        )

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

    def assert_production_safe(self) -> None:
        """Fail loudly when unsafe settings leak into a real environment.

        Called from the app lifespan. In development (``APP_ENV`` in
        ``{development, dev, local, test, ci}``) placeholders are tolerated
        so contributors can run ``uvicorn --reload`` without touching env
        files. Outside that, required secrets and provider credentials are
        validated before the API starts serving.
        """
        env = self.app_env.lower()
        mode = self.composio_mode_normalized
        offenders: list[str] = []

        if mode not in COMPOSIO_MODES:
            offenders.append("COMPOSIO_MODE")
        if mode == COMPOSIO_MODE_MOCK and env not in NON_PRODUCTION_ENVS:
            offenders.append("COMPOSIO_MODE=mock")

        if env in NON_PRODUCTION_ENVS:
            if offenders:
                raise InsecureDefaultSecretError(
                    "Refusing to start with unsafe configuration in "
                    f"app_env={self.app_env!r}: {', '.join(offenders)}. "
                    "Use COMPOSIO_MODE=real or an explicit non-production mock mode."
                )
            return
        if (self.admin_jwt_secret or "").strip() in {"", DEFAULT_ADMIN_JWT_SECRET}:
            offenders.append("ADMIN_JWT_SECRET")
        if not (self.telegram_webhook_secret or "").strip():
            offenders.append("TELEGRAM_WEBHOOK_SECRET")
        if not (self.composio_api_key or "").strip():
            offenders.append("COMPOSIO_API_KEY")
        if offenders:
            raise InsecureDefaultSecretError(
                "Refusing to start with unsafe production setting(s) in "
                f"app_env={self.app_env!r}: {', '.join(offenders)}. "
                "Override the value(s) via environment / sealed secret."
            )

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
