"""Unit tests for the Role enum and the ``require_role`` dependency."""
from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.rbac import Role, require_role, role_satisfies


def test_role_coerce_handles_unknown_and_empty() -> None:
    assert Role.coerce(None) is Role.USER
    assert Role.coerce("") is Role.USER
    assert Role.coerce("super_admin") is Role.SUPER_ADMIN
    assert Role.coerce("not-a-real-role") is Role.USER


def test_role_hierarchy() -> None:
    assert role_satisfies(Role.SUPER_ADMIN, Role.SUPPORT_ADMIN) is True
    assert role_satisfies(Role.SUPPORT_ADMIN, Role.SUPER_ADMIN) is False
    assert role_satisfies(Role.ANALYST, Role.ANALYST) is True
    assert role_satisfies(Role.USER, Role.ANALYST) is False
    assert role_satisfies(Role.BANNED, Role.USER) is False


def _build_app(role: str | None) -> FastAPI:
    """Tiny FastAPI app where ``get_current_admin`` is overridden."""
    from app.auth.dependencies import get_current_admin

    class _Stub:
        def __init__(self, role: str | None) -> None:
            self.role = role
            self.id = 1
            self.is_banned = False

    app = FastAPI()

    @app.get("/super", dependencies=[Depends(require_role("super_admin"))])
    async def _super() -> dict[str, str]:
        return {"ok": "super"}

    support_dep = require_role("support_admin", "super_admin")

    @app.get("/support")
    async def _support(admin=Depends(support_dep)) -> dict[str, str]:  # noqa: B008
        return {"ok": admin.role or ""}

    app.dependency_overrides[get_current_admin] = lambda: _Stub(role)
    return app


@pytest.mark.asyncio
async def test_super_admin_allowed_through_super_endpoint() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_build_app("super_admin")),
        base_url="http://test",
    ) as client:
        resp = await client.get("/super")
    assert resp.status_code == 200
    assert resp.json() == {"ok": "super"}


@pytest.mark.asyncio
async def test_support_admin_blocked_from_super_endpoint() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_build_app("support_admin")),
        base_url="http://test",
    ) as client:
        resp = await client.get("/super")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_super_admin_passes_support_endpoint() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_build_app("super_admin")),
        base_url="http://test",
    ) as client:
        resp = await client.get("/support")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_plain_user_rejected() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_build_app("user")),
        base_url="http://test",
    ) as client:
        resp = await client.get("/support")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unknown_role_rejected() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=_build_app("hacker")),
        base_url="http://test",
    ) as client:
        resp = await client.get("/super")
    assert resp.status_code == 403
