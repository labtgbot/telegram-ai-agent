"""Sentry initialisation for the backend.

A no-op when :pyattr:`Settings.sentry_dsn` is empty so local development and
tests don't ship spurious events to Sentry. Production environments inject the
DSN via Helm + sealed secrets — see ``deploy/helm/.../values.yaml``.
"""
from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_initialised: bool = False


def init_sentry(settings: Settings | None = None) -> bool:
    """Configure the Sentry SDK if a DSN is present.

    Returns ``True`` when initialisation actually happened (useful for
    tests).  Repeated calls short-circuit so the lifespan + ``create_app``
    paths don't double-initialise.
    """
    global _initialised
    if _initialised:
        return False
    cfg = settings or get_settings()
    dsn = (cfg.sentry_dsn or "").strip()
    if not dsn:
        logger.info("sentry.disabled")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.asyncio import AsyncioIntegration
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.httpx import HttpxIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
    except ImportError as exc:  # pragma: no cover — handled by dep pin
        logger.warning("sentry.import_failed", error=str(exc))
        return False

    from app import __version__

    release = (cfg.sentry_release or "").strip() or f"telegram-ai-agent-backend@{__version__}"
    environment = (cfg.sentry_environment or "").strip() or cfg.app_env

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=release,
        traces_sample_rate=float(cfg.sentry_traces_sample_rate),
        profiles_sample_rate=float(cfg.sentry_profiles_sample_rate),
        send_default_pii=False,
        attach_stacktrace=True,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            HttpxIntegration(),
            AsyncioIntegration(),
            LoggingIntegration(level=None, event_level=None),
        ],
    )
    sentry_sdk.set_tag("service", "backend")
    _initialised = True
    logger.info("sentry.enabled", environment=environment, release=release)
    return True


def reset_for_tests() -> None:
    """Clear the module-level guard so a fresh call to ``init_sentry`` runs."""
    global _initialised
    _initialised = False


__all__ = ["init_sentry", "reset_for_tests"]
