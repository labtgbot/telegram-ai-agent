"""FastAPI application entry point.

Exposes the ASGI ``app`` object for uvicorn:

    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.v1 import router as v1_router
from app.core.config import get_settings
from app.core.database import get_engine
from app.core.logging import configure_logging, get_logger
from app.core.redis import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)
    logger.info(
        "app.startup",
        env=settings.app_env,
        debug=settings.app_debug,
        version=__version__,
    )
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


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(
        title="Telegram AI Agent Backend",
        version=__version__,
        debug=settings.app_debug,
        lifespan=lifespan,
    )

    app.include_router(v1_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, str]:
        return {
            "name": settings.app_name,
            "version": __version__,
            "docs": "/docs",
            "health": f"{settings.api_v1_prefix}/health",
        }

    return app


app = create_app()
