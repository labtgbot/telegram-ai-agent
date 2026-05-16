"""Tests for /api/v1/legal/* and the root /privacy, /terms endpoints.

The handlers read Markdown files from disk; they don't touch Postgres or
Redis, so the tests run without database fixtures.
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
    engine = MagicMock()
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 1))

    @asynccontextmanager
    async def _connect(*args: Any, **kwargs: Any):
        yield conn

    engine.connect = _connect
    engine.dispose = AsyncMock()
    return engine


async def _make_client(fake_engine: MagicMock):
    from app.main import app

    return app


async def test_legal_index_lists_documents(fake_engine: MagicMock) -> None:
    with patch("app.main.get_engine", return_value=fake_engine):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/legal")
    assert resp.status_code == 200
    body = resp.json()
    slugs = {doc["slug"] for doc in body["documents"]}
    assert {"privacy", "terms", "dpa", "subprocessors", "age-verification"} <= slugs


async def test_legal_privacy_json(fake_engine: MagicMock) -> None:
    with patch("app.main.get_engine", return_value=fake_engine):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/legal/privacy")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == "privacy"
    assert body["title"] == "Privacy Policy"
    assert "Privacy Policy" in body["body"]
    assert body["last_updated"] is not None


async def test_legal_terms_markdown_via_accept_header(
    fake_engine: MagicMock,
) -> None:
    with patch("app.main.get_engine", return_value=fake_engine):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/v1/legal/terms",
                headers={"Accept": "text/markdown"},
            )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "Terms of Service" in resp.text


async def test_legal_unknown_slug_returns_404(fake_engine: MagicMock) -> None:
    with patch("app.main.get_engine", return_value=fake_engine):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/legal/does-not-exist")
    assert resp.status_code == 404


async def test_root_privacy_endpoint(fake_engine: MagicMock) -> None:
    with patch("app.main.get_engine", return_value=fake_engine):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/privacy")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "Privacy Policy" in resp.text


async def test_root_terms_endpoint(fake_engine: MagicMock) -> None:
    with patch("app.main.get_engine", return_value=fake_engine):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/terms")
    assert resp.status_code == 200
    assert "Terms of Service" in resp.text


async def test_legal_dpa_contains_annexes(fake_engine: MagicMock) -> None:
    with patch("app.main.get_engine", return_value=fake_engine):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/v1/legal/dpa")
    assert resp.status_code == 200
    body = resp.json()
    assert "Annex I" in body["body"]
    assert "Annex II" in body["body"]
    assert "Annex III" in body["body"]
