"""Endpoint-level tests for ``/api/v1/auth/*`` with ORM and Redis mocked.

These exercise dependency wiring, error mapping, and the JWT round-trip.
DB and Redis interactions are stubbed with in-memory fakes so the suite runs
without external services.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient

BOT_TOKEN = "1234567890:TEST-AAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
JWT_SECRET = "test-secret"


# ---------------------------------------------------------------- fixtures


class _Settings:
    app_env = "development"
    app_debug = True
    telegram_bot_token = BOT_TOKEN
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
    def __init__(
        self,
        *,
        id: int = 1,
        telegram_id: int,
        role: str = "super_admin",
        is_banned: bool = False,
        totp_enabled: bool = False,
        totp_secret: str | None = None,
    ) -> None:
        self.id = id
        self.telegram_id = telegram_id
        self.username = "alice"
        self.first_name = "Alice"
        self.last_name = None
        self.language_code = "en"
        self.referral_code = "REF-1"
        self.role = role
        self.is_banned = is_banned
        self.totp_enabled = totp_enabled
        self.totp_secret = totp_secret
        self.is_premium = False
        self.last_active_at = None
        self.last_login_at = None


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def set(
        self, key: str, value: str, *, ex: int | None = None, nx: bool = False
    ) -> bool:
        if nx and key in self.store:
            return False
        self.store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self.store.get(key)

    async def delete(self, *keys: str) -> int:
        n = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                n += 1
        return n

    async def incr(self, key: str) -> int:
        v = int(self.store.get(key, 0)) + 1
        self.store[key] = str(v)
        return v

    async def expire(self, key: str, seconds: int) -> bool:
        return key in self.store


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def fake_settings() -> _Settings:
    return _Settings()


@pytest.fixture
def stub_user() -> FakeUser:
    return FakeUser(telegram_id=42, role="super_admin")


@pytest.fixture
def build_app(monkeypatch, fake_settings, fake_redis, stub_user):
    """Return a callable that builds an app wired with overridable stubs."""
    from app.api.v1 import auth as auth_module
    from app.auth import dependencies as deps
    from app.core import redis as redis_module
    from app.main import create_app
    from app.services import users as users_module

    user_store: dict[int, FakeUser] = {stub_user.telegram_id: stub_user}

    async def fake_find_by_id(session, user_id):  # type: ignore[no-untyped-def]
        for u in user_store.values():
            if u.id == user_id:
                return u
        return None

    async def fake_find_by_telegram_id(session, telegram_id):  # type: ignore[no-untyped-def]
        return user_store.get(telegram_id)

    async def fake_upsert(session, *, telegram_user, super_admin_ids):  # type: ignore[no-untyped-def]
        tid = int(telegram_user["id"])
        existing = user_store.get(tid)
        if existing is None:
            existing = FakeUser(
                id=tid,
                telegram_id=tid,
                role="user",
            )
            existing.referral_code = f"REF-{tid}"
            user_store[tid] = existing
            return existing, True
        return existing, False

    async def fake_record_login(session, user):  # type: ignore[no-untyped-def]
        user.last_login_at = time.time()

    async def fake_get_session():  # type: ignore[no-untyped-def]
        yield None

    monkeypatch.setattr(users_module, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(
        users_module, "find_user_by_telegram_id", fake_find_by_telegram_id
    )
    monkeypatch.setattr(users_module, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(users_module, "record_admin_login", fake_record_login)
    # The auth router imports symbols directly — patch them at the call site.
    monkeypatch.setattr(auth_module, "find_user_by_telegram_id", fake_find_by_telegram_id)
    monkeypatch.setattr(auth_module, "record_admin_login", fake_record_login)
    monkeypatch.setattr(deps, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(deps, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "get_session", fake_get_session)
    monkeypatch.setattr(redis_module, "get_redis", lambda: fake_redis)
    monkeypatch.setattr("app.auth.dependencies.get_session", fake_get_session)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: fake_settings, raising=True
    )
    monkeypatch.setattr(
        "app.auth.dependencies.get_settings",
        lambda: fake_settings,
    )
    monkeypatch.setattr(
        "app.api.v1.auth.get_redis", lambda: fake_redis, raising=False
    )

    app = create_app()

    # Override dependencies that resolve via Depends() at request time.
    from app.auth.dependencies import _settings_dep
    from app.core.database import get_session as real_get_session

    async def _yield_none():
        yield None

    app.dependency_overrides[real_get_session] = _yield_none
    app.dependency_overrides[_settings_dep] = lambda: fake_settings
    from app.api.v1.auth import _redis_dep

    app.dependency_overrides[_redis_dep] = lambda: fake_redis

    return app, user_store


def _build_init_data(telegram_id: int = 42) -> str:
    user = {"id": telegram_id, "first_name": "Alice", "username": "alice"}
    pairs = [
        ("query_id", "AAA"),
        ("user", json.dumps(user, separators=(",", ":"))),
        ("auth_date", str(int(time.time()))),
    ]
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs, key=lambda p: p[0]))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    pairs.append(("hash", digest))
    return urlencode(pairs)


async def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --------------------------------------------------------- tests

@pytest.mark.asyncio
async def test_telegram_verify_creates_user(build_app) -> None:
    app, store = build_app
    init = _build_init_data(telegram_id=4242)
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/auth/telegram/verify",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["telegram_id"] == 4242
    assert 4242 in store


@pytest.mark.asyncio
async def test_telegram_verify_rejects_tampered(build_app) -> None:
    app, _ = build_app
    init = _build_init_data().replace("Alice", "Mallory")
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/auth/telegram/verify",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_init_data"


@pytest.mark.asyncio
async def test_telegram_verify_rejects_missing_header(build_app) -> None:
    app, _ = build_app
    async with await _client(app) as c:
        resp = await c.post("/api/v1/auth/telegram/verify")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"


@pytest.mark.asyncio
async def test_admin_login_round_trip_returns_tokens(build_app) -> None:
    app, _ = build_app
    async with await _client(app) as c:
        req = await c.post(
            "/api/v1/auth/admin/login/request",
            json={"telegram_id": 42},
        )
        assert req.status_code == 200, req.text
        code = req.json()["code"]
        assert code

        verify = await c.post(
            "/api/v1/auth/admin/login/verify",
            json={"telegram_id": 42, "code": code},
        )
        assert verify.status_code == 200, verify.text
        tokens = verify.json()
        access = tokens["access_token"]
        refresh = tokens["refresh_token"]
        assert access and refresh
        assert tokens["token_type"] == "Bearer"

        me = await c.get(
            "/api/v1/auth/admin/me",
            headers={"Authorization": f"Bearer {access}"},
        )
        assert me.status_code == 200
        assert me.json()["user"]["telegram_id"] == 42

        refreshed = await c.post(
            "/api/v1/auth/admin/refresh",
            json={"refresh_token": refresh},
        )
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"]


@pytest.mark.asyncio
async def test_admin_login_request_rejects_non_admin(build_app) -> None:
    app, store = build_app
    store[99] = FakeUser(id=99, telegram_id=99, role="user")
    async with await _client(app) as c:
        req = await c.post(
            "/api/v1/auth/admin/login/request",
            json={"telegram_id": 99},
        )
    assert req.status_code == 403
    assert req.json()["detail"] == "not_an_admin"


@pytest.mark.asyncio
async def test_admin_login_verify_invalid_code(build_app) -> None:
    app, _ = build_app
    async with await _client(app) as c:
        await c.post(
            "/api/v1/auth/admin/login/request",
            json={"telegram_id": 42},
        )
        resp = await c.post(
            "/api/v1/auth/admin/login/verify",
            json={"telegram_id": 42, "code": "000000"},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "login_code_invalid"


@pytest.mark.asyncio
async def test_admin_login_requires_totp_when_enabled(build_app) -> None:
    app, store = build_app
    import pyotp

    user = store[42]
    user.totp_enabled = True
    user.totp_secret = pyotp.random_base32()

    async with await _client(app) as c:
        req = await c.post(
            "/api/v1/auth/admin/login/request",
            json={"telegram_id": 42},
        )
        code = req.json()["code"]

        # Missing TOTP — rejected.
        without = await c.post(
            "/api/v1/auth/admin/login/verify",
            json={"telegram_id": 42, "code": code},
        )
        assert without.status_code == 401
        assert without.json()["detail"] == "totp_required"

        # Re-request a fresh code (previous one was consumed by the failed
        # verify check that happens *before* the TOTP gate? No — TOTP gate
        # runs *after* successful verify, so the code is already consumed.
        req2 = await c.post(
            "/api/v1/auth/admin/login/request",
            json={"telegram_id": 42},
        )
        code2 = req2.json()["code"]
        totp_code = pyotp.TOTP(user.totp_secret).now()
        ok = await c.post(
            "/api/v1/auth/admin/login/verify",
            json={"telegram_id": 42, "code": code2, "totp_code": totp_code},
        )
        assert ok.status_code == 200


@pytest.mark.asyncio
async def test_refresh_with_invalid_token(build_app) -> None:
    app, _ = build_app
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/auth/admin/refresh",
            json={"refresh_token": "garbage"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_admin_me_requires_bearer(build_app) -> None:
    app, _ = build_app
    async with await _client(app) as c:
        resp = await c.get("/api/v1/auth/admin/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_authorization"
