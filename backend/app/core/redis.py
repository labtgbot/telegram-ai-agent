"""Async Redis client lifecycle.

A single shared :class:`redis.asyncio.Redis` instance is created lazily so that
import-time has no side effects (tests can patch the URL via env vars before
the first call).
"""
from __future__ import annotations

from redis.asyncio import Redis, from_url

from app.core.config import get_settings

_redis: Redis | None = None


def get_redis() -> Redis:
    """Return the process-wide Redis client, creating it on first call."""
    global _redis
    if _redis is None:
        _redis = from_url(
            get_settings().redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """Close the shared client (call on application shutdown)."""
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
