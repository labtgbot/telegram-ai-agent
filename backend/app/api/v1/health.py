"""Health-check endpoints.

* ``/health`` — deep check: pings PostgreSQL and Redis, returns 200 only if
  both are reachable. Used by load balancers and uptime monitors.
* ``/health/live`` — cheap liveness probe (no I/O). Used by Kubernetes.
"""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import get_engine
from app.core.logging import get_logger
from app.core.redis import get_redis

router = APIRouter(tags=["health"])
logger = get_logger(__name__)


class ComponentStatus(BaseModel):
    status: Literal["ok", "error", "skipped"]
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    components: dict[str, ComponentStatus]


async def _check_database(timeout: float) -> ComponentStatus:
    try:
        engine = get_engine()
        async with asyncio.timeout(timeout):
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        return ComponentStatus(status="ok")
    except Exception as exc:
        logger.warning("health.db_check_failed", error=str(exc))
        return ComponentStatus(status="error", error=str(exc))


async def _check_redis(timeout: float) -> ComponentStatus:
    try:
        client = get_redis()
        async with asyncio.timeout(timeout):
            pong = await client.ping()
        if not pong:
            return ComponentStatus(status="error", error="ping returned falsy")
        return ComponentStatus(status="ok")
    except Exception as exc:
        logger.warning("health.redis_check_failed", error=str(exc))
        return ComponentStatus(status="error", error=str(exc))


@router.get(
    "/health/live",
    response_model=HealthResponse,
    summary="Liveness probe",
)
async def live() -> HealthResponse:
    """Cheap liveness probe — does not touch external dependencies."""
    from app import __version__

    return HealthResponse(
        status="ok",
        version=__version__,
        components={},
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Readiness probe with DB + Redis checks",
)
async def health() -> JSONResponse:
    from app import __version__

    settings = get_settings()
    timeout = settings.health_check_timeout

    db_status, redis_status = await asyncio.gather(
        _check_database(timeout),
        _check_redis(timeout),
    )

    components = {"database": db_status, "redis": redis_status}
    overall: Literal["ok", "degraded"] = (
        "ok" if all(c.status == "ok" for c in components.values()) else "degraded"
    )
    payload = HealthResponse(
        status=overall, version=__version__, components=components
    )
    http_status = (
        status.HTTP_200_OK if overall == "ok" else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=http_status, content=payload.model_dump())
