"""Smoke tests for the FastAPI app — no external services required.

We patch the engine and Redis client so the tests run in any environment
(including CI without Postgres on the network path for unit tests).
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def fake_engine() -> MagicMock:
    """An engine whose ``.connect()`` yields a connection that returns 1."""
    engine = MagicMock()
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 1))

    @asynccontextmanager
    async def _connect(*args: Any, **kwargs: Any):
        yield conn

    engine.connect = _connect
    engine.dispose = AsyncMock()
    return engine


@pytest.fixture
def fake_redis_ok() -> MagicMock:
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def fake_redis_fail() -> MagicMock:
    redis = MagicMock()
    redis.ping = AsyncMock(side_effect=ConnectionError("no redis"))
    redis.aclose = AsyncMock()
    return redis


@pytest.fixture
def fake_engine_fail() -> MagicMock:
    engine = MagicMock()

    @asynccontextmanager
    async def _connect(*args: Any, **kwargs: Any):
        raise ConnectionError("no postgres")
        yield  # pragma: no cover

    engine.connect = _connect
    engine.dispose = AsyncMock()
    return engine


async def _client() -> AsyncClient:
    from app.main import app

    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_root_endpoint(fake_engine: MagicMock, fake_redis_ok: MagicMock) -> None:
    with (
        patch("app.api.v1.health.get_engine", return_value=fake_engine),
        patch("app.api.v1.health.get_redis", return_value=fake_redis_ok),
        patch("app.main.get_engine", return_value=fake_engine),
    ):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert "name" in body
        assert "version" in body
        assert body["health"] == "/api/v1/health"


async def test_liveness_endpoint(fake_engine: MagicMock, fake_redis_ok: MagicMock) -> None:
    with (
        patch("app.api.v1.health.get_engine", return_value=fake_engine),
        patch("app.api.v1.health.get_redis", return_value=fake_redis_ok),
        patch("app.main.get_engine", return_value=fake_engine),
    ):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health/live")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


async def test_health_ok(fake_engine: MagicMock, fake_redis_ok: MagicMock) -> None:
    with (
        patch("app.api.v1.health.get_engine", return_value=fake_engine),
        patch("app.api.v1.health.get_redis", return_value=fake_redis_ok),
        patch("app.main.get_engine", return_value=fake_engine),
    ):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["components"]["database"]["status"] == "ok"
        assert body["components"]["redis"]["status"] == "ok"


async def test_health_degraded_when_redis_down(
    fake_engine: MagicMock, fake_redis_fail: MagicMock
) -> None:
    with (
        patch("app.api.v1.health.get_engine", return_value=fake_engine),
        patch("app.api.v1.health.get_redis", return_value=fake_redis_fail),
        patch("app.main.get_engine", return_value=fake_engine),
    ):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["components"]["database"]["status"] == "ok"
        assert body["components"]["redis"]["status"] == "error"


async def test_health_degraded_when_redis_ping_returns_sync_false(
    fake_engine: MagicMock,
) -> None:
    redis = MagicMock()
    redis.ping.return_value = False
    redis.aclose = AsyncMock()

    with (
        patch("app.api.v1.health.get_engine", return_value=fake_engine),
        patch("app.api.v1.health.get_redis", return_value=redis),
        patch("app.main.get_engine", return_value=fake_engine),
    ):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["components"]["database"]["status"] == "ok"
        assert body["components"]["redis"]["status"] == "error"
        assert body["components"]["redis"]["error"] == "ping returned falsy"


async def test_health_degraded_when_db_down(
    fake_engine_fail: MagicMock, fake_redis_ok: MagicMock
) -> None:
    with (
        patch("app.api.v1.health.get_engine", return_value=fake_engine_fail),
        patch("app.api.v1.health.get_redis", return_value=fake_redis_ok),
        patch("app.main.get_engine", return_value=fake_engine_fail),
    ):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/health")
        assert resp.status_code == 503
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["components"]["database"]["status"] == "error"
        assert body["components"]["redis"]["status"] == "ok"
