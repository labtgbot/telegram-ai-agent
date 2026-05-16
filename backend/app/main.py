"""FastAPI application entry point.

Exposes the ASGI ``app`` object for uvicorn:

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from app import __version__
from app.api.v1 import router as v1_router
from app.api.v1.bot import close_bot_client, get_bot_client
from app.api.v1.generate import close_composio_client
from app.api.v1.legal import load_legal_document
from app.bot.commands import set_bot_commands
from app.core.config import get_settings
from app.core.database import get_engine
from app.core.logging import configure_logging, get_logger
from app.core.metrics import setup_metrics
from app.core.redis import close_redis
from app.core.sentry import init_sentry


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)
    settings.assert_production_safe()
    logger.info(
        "app.startup",
        env=settings.app_env,
        debug=settings.app_debug,
        version=__version__,
    )
    if settings.telegram_bot_token and settings.telegram_set_commands_on_startup:
        try:
            await set_bot_commands(get_bot_client())
        except Exception as exc:  # noqa: BLE001 — never block startup on Telegram
            logger.warning("app.startup.set_commands_failed", error=str(exc))
    try:
        yield
    finally:
        logger.info("app.shutdown")
        try:
            engine = get_engine()
            await engine.dispose()
        except Exception as exc:
            logger.warning("app.shutdown.engine_dispose_failed", error=str(exc))
        try:
            await close_redis()
        except Exception as exc:
            logger.warning("app.shutdown.redis_close_failed", error=str(exc))
        try:
            await close_bot_client()
        except Exception as exc:
            logger.warning("app.shutdown.bot_client_close_failed", error=str(exc))
        try:
            await close_composio_client()
        except Exception as exc:
            logger.warning("app.shutdown.composio_close_failed", error=str(exc))


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    init_sentry(settings)

    app = FastAPI(
        title="Telegram AI Agent Backend",
        version=__version__,
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    setup_metrics(app, settings)

    app.include_router(v1_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": f"{settings.api_v1_prefix}/health",
            "privacy": "/privacy",
            "terms": "/terms",
        }

    def _legal_text(slug: str) -> PlainTextResponse:
        doc = load_legal_document(slug)
        return PlainTextResponse(
            content=doc.body, media_type="text/markdown; charset=utf-8"
        )

    @app.get("/privacy", include_in_schema=False)
    async def privacy_policy() -> PlainTextResponse:
        """Public Privacy Policy (Markdown). Referenced by the bot's /privacy command."""
        return _legal_text("privacy")

    @app.get("/terms", include_in_schema=False)
    async def terms_of_service() -> PlainTextResponse:
        """Public Terms of Service (Markdown). Referenced by the bot's /terms command."""
        return _legal_text("terms")

    return app


app = create_app()
