"""Endpoint-level RBAC tests for ``/api/v1/admin/pricing/*``."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

JWT_SECRET = "test-secret"


class _Settings:
    app_env = "development"
    app_debug = True
    telegram_bot_token = "1:TEST-AAA"
    telegram_init_data_max_age = 600
    admin_jwt_secret = JWT_SECRET
    admin_jwt_algorithm = "HS256"
    admin_access_token_ttl = 60
    admin_refresh_token_ttl = 600
    admin_login_code_ttl = 60
    admin_login_code_length = 6
    admin_login_max_attempts = 5
    admin_super_telegram_ids = ""

    @property
    def is_development(self) -> bool:
        return True

    @property
    def super_admin_ids(self) -> set[int]:
        return set()


class FakeUser:
    def __init__(self, *, id: int, telegram_id: int, role: str = "analyst") -> None:
        self.id = id
        self.telegram_id = telegram_id
        self.role = role
        self.username = f"u{telegram_id}"
        self.is_premium = False
        self.is_banned = False


class FakeSession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class FakeAuditLog:
    def __init__(self) -> None:
        self.id = 1
        self.admin_id = 1
        self.payload = {"diff": {}, "config": {}}
        self.ip_address = None
        self.user_agent = None
        self.created_at = datetime.now(UTC)


class _FakePage:
    items: list[Any] = [FakeAuditLog()]
    total = 1
    page = 1
    limit = 25
    has_more = False


@pytest.fixture
def admin_analyst() -> FakeUser:
    return FakeUser(id=2, telegram_id=200, role="analyst")


@pytest.fixture
def admin_super() -> FakeUser:
    return FakeUser(id=1, telegram_id=100, role="super_admin")


@pytest.fixture
def build_app(monkeypatch, admin_super):
    from app.api.v1 import admin_pricing as router_module
    from app.auth.dependencies import _settings_dep, get_current_admin
    from app.core.database import get_session
    from app.main import create_app
    from app.services.pricing import PricingConfig, PricingPackageOverride

    session = FakeSession()
    state: dict[str, Any] = {"current_admin": admin_super, "session": session}

    async def fake_load_pricing_config(_session):
        return PricingConfig(
            packages=(
                PricingPackageOverride(
                    code="starter",
                    title="Starter",
                    description="Starter pack",
                    tokens=100,
                    stars=10,
                ),
            )
        )

    async def fake_list_audit_log(_session, **_kwargs):
        return _FakePage()

    monkeypatch.setattr(router_module, "load_pricing_config", fake_load_pricing_config)
    monkeypatch.setattr(router_module, "list_audit_log", fake_list_audit_log)

    app = create_app()

    async def _yield_session():
        yield session

    async def _yield_admin():
        return state["current_admin"]

    app.dependency_overrides[get_session] = _yield_session
    app.dependency_overrides[_settings_dep] = lambda: _Settings()
    app.dependency_overrides[get_current_admin] = _yield_admin

    state["app"] = app
    return state


async def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/pricing",
        "/api/v1/admin/pricing/history",
    ],
)
async def test_pricing_reads_forbidden_for_analyst(build_app, admin_analyst, path) -> None:
    build_app["current_admin"] = admin_analyst
    async with await _client(build_app["app"]) as c:
        resp = await c.get(path)
    assert resp.status_code == 403
