"""Endpoint-level tests for ``/api/v1/admin/system/*`` (issue #29).

Stubs the service layer so we can verify the FastAPI surface in
isolation: RBAC tiers, payload validation, error mapping, audit-log
writes and request metadata propagation.

Mirrors the build-app pattern from ``test_admin_broadcasts_endpoints.py``
to keep the suite fast and PostgreSQL-free.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    def __init__(self, *, id: int, telegram_id: int, role: str = "user") -> None:
        self.id = id
        self.telegram_id = telegram_id
        self.role = role
        self.username = f"u{telegram_id}"
        self.is_premium = False
        self.is_banned = False


class FakeAuditLog:
    def __init__(
        self,
        *,
        admin_id: int,
        action: str,
        payload: dict[str, Any] | None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        target_user_id: int | None = None,
    ) -> None:
        self.admin_id = admin_id
        self.target_user_id = target_user_id
        self.action = action
        self.payload = payload
        self.ip_address = ip_address
        self.user_agent = user_agent


class FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


@dataclass
class _FakeAdminPage:
    items: list[Any]
    total: int
    page: int
    limit: int
    has_more: bool


@pytest.fixture
def admin_super() -> FakeUser:
    return FakeUser(id=1, telegram_id=100, role="super_admin")


@pytest.fixture
def admin_support() -> FakeUser:
    return FakeUser(id=2, telegram_id=200, role="support_admin")


@pytest.fixture
def admin_analyst() -> FakeUser:
    return FakeUser(id=3, telegram_id=300, role="analyst")


@pytest.fixture
def build_app(monkeypatch, admin_super):
    """ASGI app with ``admin_system`` service hooks stubbed in memory."""
    from app.api.v1 import admin_system as router_module
    from app.auth.dependencies import _settings_dep, get_current_admin
    from app.core.database import get_session
    from app.main import create_app
    from app.services.admin_system import (
        AdminRoleChangeError,
        AdminUserRow,
        ComposioState,
        InvalidSettingPayloadError,
        MaintenanceState,
    )

    session = FakeSession()
    state: dict[str, Any] = {
        "maintenance": MaintenanceState(
            enabled=False, message=None, updated_at=None, updated_by=None
        ),
        "rate_limits": {
            "plans": {"free": {"messages": {"limit": 60, "window_seconds": 60}}},
            "overrides": {},
            "defaults": {"free": {"messages": {"limit": 60, "window_seconds": 60}}},
            "updated_at": None,
            "updated_by": None,
        },
        "composio": ComposioState(enabled_tools=[], config={}, updated_at=None, updated_by=None),
        "admins": {
            1: AdminUserRow(
                id=1, telegram_id=100, username="super", first_name="S", last_name=None,
                role="super_admin", is_banned=False,
                last_login_at=None, last_active_at=None,
                created_at=datetime.now(UTC),
            ),
            2: AdminUserRow(
                id=2, telegram_id=200, username="support", first_name="P", last_name=None,
                role="support_admin", is_banned=False,
                last_login_at=None, last_active_at=None,
                created_at=datetime.now(UTC),
            ),
        },
        "audit_log": [],
        "current_admin": admin_super,
        "session": session,
    }

    # ---------- maintenance
    async def fake_get_maintenance(_session):
        return state["maintenance"]

    async def fake_update_maintenance(_session, *, admin, enabled, message=None, ip_address=None, user_agent=None):
        if message is not None and len(message) > 2000:
            raise InvalidSettingPayloadError("message exceeds 2000 characters")
        next_state = MaintenanceState(
            enabled=bool(enabled),
            message=message,
            updated_at=datetime.now(UTC),
            updated_by=admin.id,
        )
        state["maintenance"] = next_state
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="settings.maintenance.update",
                payload={"enabled": next_state.enabled, "message": message},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return next_state

    # ---------- rate limits
    async def fake_get_rate_limits(_session):
        return state["rate_limits"]

    async def fake_update_rate_limits(_session, *, admin, overrides, ip_address=None, user_agent=None):
        if overrides is not None and not isinstance(overrides, dict):
            raise InvalidSettingPayloadError("overrides must be mapping")
        if overrides is not None:
            for plan, rules in overrides.items():
                for action, rule in rules.items():
                    if rule.get("limit", 0) <= 0 or rule.get("window_seconds", 0) <= 0:
                        raise InvalidSettingPayloadError(
                            f"rate_limits[{plan!r}][{action!r}] requires positive values"
                        )
        cleaned = overrides or {}
        state["rate_limits"] = {
            **state["rate_limits"],
            "overrides": cleaned,
            "updated_at": datetime.now(UTC),
            "updated_by": admin.id,
        }
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="settings.rate_limits.update",
                payload={"after": cleaned},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return state["rate_limits"]

    # ---------- composio
    async def fake_get_composio(_session):
        return state["composio"]

    async def fake_update_composio(_session, *, admin, enabled_tools, config=None, ip_address=None, user_agent=None):
        if not isinstance(enabled_tools, list):
            raise InvalidSettingPayloadError("enabled_tools must be a list")
        cleaned: list[str] = []
        for tool in enabled_tools:
            if not isinstance(tool, str):
                raise InvalidSettingPayloadError("enabled_tools must contain strings")
            slug = tool.strip()
            if slug and slug not in cleaned:
                cleaned.append(slug)
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise InvalidSettingPayloadError("config must be mapping")
        next_state = ComposioState(
            enabled_tools=cleaned,
            config=config,
            updated_at=datetime.now(UTC),
            updated_by=admin.id,
        )
        state["composio"] = next_state
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="settings.composio.update",
                payload={"enabled_tools": cleaned},
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        return next_state

    # ---------- admins
    async def fake_list_admins(_session, *, role=None, page=1, limit=25):
        items = sorted(state["admins"].values(), key=lambda r: r.id)
        if role:
            if role not in {"super_admin", "support_admin", "analyst"}:
                raise InvalidSettingPayloadError(f"unsupported role={role!r}")
            items = [u for u in items if u.role == role]
        total = len(items)
        items = items[(page - 1) * limit : page * limit]
        return _FakeAdminPage(items=items, total=total, page=page, limit=limit, has_more=(page * limit) < total)

    async def fake_update_admin_role(_session, *, admin, target_user_id, role, ip_address=None, user_agent=None):
        if role not in {"super_admin", "support_admin", "analyst", "user"}:
            raise InvalidSettingPayloadError(f"unsupported role={role!r}")
        row = state["admins"].get(target_user_id)
        if row is None:
            raise AdminRoleChangeError(f"user {target_user_id} not found")
        if row.role == role:
            return row
        if row.role == "super_admin" and role != "super_admin":
            supers = [u for u in state["admins"].values() if u.role == "super_admin"]
            if len(supers) <= 1:
                raise AdminRoleChangeError("cannot demote the last super_admin")
        updated = AdminUserRow(
            id=row.id,
            telegram_id=row.telegram_id,
            username=row.username,
            first_name=row.first_name,
            last_name=row.last_name,
            role=role,
            is_banned=row.is_banned,
            last_login_at=row.last_login_at,
            last_active_at=row.last_active_at,
            created_at=row.created_at,
        )
        state["admins"][target_user_id] = updated
        state["audit_log"].append(
            FakeAuditLog(
                admin_id=admin.id,
                action="admin.role.update",
                payload={"user_id": row.id, "before": row.role, "after": role},
                ip_address=ip_address,
                user_agent=user_agent,
                target_user_id=row.id,
            )
        )
        return updated

    monkeypatch.setattr(router_module, "get_maintenance_state", fake_get_maintenance)
    monkeypatch.setattr(router_module, "update_maintenance_state", fake_update_maintenance)
    monkeypatch.setattr(router_module, "get_rate_limits", fake_get_rate_limits)
    monkeypatch.setattr(router_module, "update_rate_limits", fake_update_rate_limits)
    monkeypatch.setattr(router_module, "get_composio_state", fake_get_composio)
    monkeypatch.setattr(router_module, "update_composio_state", fake_update_composio)
    monkeypatch.setattr(router_module, "list_admin_users", fake_list_admins)
    monkeypatch.setattr(router_module, "update_admin_role", fake_update_admin_role)

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


# ---------------------------------------------------------------- maintenance


@pytest.mark.asyncio
async def test_get_maintenance_state_returns_default(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.get("/api/v1/admin/system/maintenance")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is False
    assert body["message"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/admin/system/maintenance",
        "/api/v1/admin/system/rate-limits",
        "/api/v1/admin/system/composio",
        "/api/v1/admin/system/admins",
    ],
)
async def test_system_reads_forbidden_for_support_admin(build_app, admin_support, path) -> None:
    build_app["current_admin"] = admin_support
    async with await _client(build_app["app"]) as c:
        resp = await c.get(path)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_maintenance_state_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/maintenance",
            json={"enabled": True, "message": "Back at 18:00 UTC"},
            headers={"X-Forwarded-For": "1.2.3.4", "User-Agent": "tests/1.0"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["message"] == "Back at 18:00 UTC"
    audit = build_app["audit_log"][-1]
    assert audit.action == "settings.maintenance.update"
    assert audit.ip_address == "127.0.0.1"
    assert audit.user_agent == "tests/1.0"
    assert build_app["session"].committed is True


@pytest.mark.asyncio
async def test_update_maintenance_rejects_long_message(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/maintenance",
            json={"enabled": True, "message": "x" * 5000},
        )
    # Pydantic max_length=2000 catches this at validation time
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_maintenance_forbidden_for_analyst(build_app, admin_analyst) -> None:
    build_app["current_admin"] = admin_analyst
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/maintenance",
            json={"enabled": True},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_maintenance_forbidden_for_support_admin(build_app, admin_support) -> None:
    build_app["current_admin"] = admin_support
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/maintenance",
            json={"enabled": True},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------- rate limits


@pytest.mark.asyncio
async def test_get_rate_limits_returns_defaults(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.get("/api/v1/admin/system/rate-limits")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "plans" in body
    assert "defaults" in body


@pytest.mark.asyncio
async def test_update_rate_limits_persists_and_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/rate-limits",
            json={
                "overrides": {
                    "free": {"messages": {"limit": 30, "window_seconds": 60}}
                }
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overrides"] == {
        "free": {"messages": {"limit": 30, "window_seconds": 60}}
    }
    assert build_app["audit_log"][-1].action == "settings.rate_limits.update"


@pytest.mark.asyncio
async def test_update_rate_limits_rejects_negative_values(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/rate-limits",
            json={
                "overrides": {
                    "free": {"messages": {"limit": -1, "window_seconds": 60}}
                }
            },
        )
    assert resp.status_code == 400
    assert "positive" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_rate_limits_forbidden_for_support_admin(build_app, admin_support) -> None:
    build_app["current_admin"] = admin_support
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/rate-limits",
            json={"overrides": None},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_rate_limits_accepts_null_overrides(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/rate-limits",
            json={"overrides": None},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["overrides"] == {}


# ---------------------------------------------------------------- composio


@pytest.mark.asyncio
async def test_get_composio_state_returns_default(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.get("/api/v1/admin/system/composio")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled_tools"] == []
    assert body["config"] == {}


@pytest.mark.asyncio
async def test_update_composio_persists_and_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/composio",
            json={
                "enabled_tools": ["gmail.send_email", " github.create_issue ", "gmail.send_email"],
                "config": {"gmail.send_email": {"signature": "Cheers"}},
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # duplicate dropped, whitespace trimmed
    assert body["enabled_tools"] == ["gmail.send_email", "github.create_issue"]
    assert build_app["audit_log"][-1].action == "settings.composio.update"


@pytest.mark.asyncio
async def test_composio_forbidden_for_analyst(build_app, admin_analyst) -> None:
    build_app["current_admin"] = admin_analyst
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/composio",
            json={"enabled_tools": []},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_composio_forbidden_for_support_admin(build_app, admin_support) -> None:
    build_app["current_admin"] = admin_support
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/composio",
            json={"enabled_tools": []},
        )
    assert resp.status_code == 403


# ---------------------------------------------------------------- admins


@pytest.mark.asyncio
async def test_list_admins_returns_assignable_roles(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.get("/api/v1/admin/system/admins")
    body = resp.json()
    assert resp.status_code == 200, resp.text
    assert body["total"] == 2
    assert set(body["assignable_roles"]) == {"analyst", "support_admin", "super_admin", "user"}


@pytest.mark.asyncio
async def test_update_admin_role_audits(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/admins/2/role",
            json={"role": "analyst"},
            headers={"X-Forwarded-For": "9.8.7.6"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "analyst"
    audit = build_app["audit_log"][-1]
    assert audit.action == "admin.role.update"
    assert audit.target_user_id == 2
    assert audit.ip_address == "127.0.0.1"


@pytest.mark.asyncio
async def test_update_admin_role_allows_demoting_to_user(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/admins/2/role",
            json={"role": "user"},
        )

    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "user"
    assert build_app["admins"][2].role == "user"
    audit = build_app["audit_log"][-1]
    assert audit.action == "admin.role.update"
    assert audit.payload == {"user_id": 2, "before": "support_admin", "after": "user"}


@pytest.mark.asyncio
async def test_update_admin_role_404_when_missing(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/admins/9999/role",
            json={"role": "analyst"},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "user_not_found"


@pytest.mark.asyncio
async def test_update_admin_role_refuses_demoting_last_super_admin(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/admins/1/role",
            json={"role": "analyst"},
        )
    assert resp.status_code == 409
    assert "cannot demote" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_update_admin_role_rejects_unknown_role(build_app) -> None:
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/admins/2/role",
            json={"role": "rocket-launcher"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_role_change_forbidden_for_support_admin(build_app, admin_support) -> None:
    build_app["current_admin"] = admin_support
    async with await _client(build_app["app"]) as c:
        resp = await c.put(
            "/api/v1/admin/system/admins/2/role",
            json={"role": "analyst"},
        )
    assert resp.status_code == 403
