"""Endpoint tests for the Phase-4 age-verification stub.

The route is gated behind ``compliance_age_gate_enabled`` and a configured
provider. These tests pin the public contract:

* off-by-default → 404 on both ``GET`` and ``POST``;
* ``GET`` when enabled returns the current state (always ``verified=False``);
* ``POST`` with ``self_declared`` in dev → 200 + ``verified=True``;
* ``POST`` with a non-implemented provider → 501;
* ``POST`` with ``self_declared`` outside dev → 403 (foot-gun guard);
* ``POST`` with ``confirmed_18_plus=false`` → 400.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient

BOT_TOKEN = "1234567890:TEST-AAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
JWT_SECRET = "test-secret"


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
    compliance_age_gate_enabled = False
    compliance_age_gate_provider = "self_declared"

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "local"}

    @property
    def super_admin_ids(self) -> set[int]:
        return set()


class FakeUser:
    def __init__(self, *, id: int, telegram_id: int) -> None:
        self.id = id
        self.telegram_id = telegram_id
        self.username = "alice"
        self.first_name = "Alice"
        self.last_name = None
        self.language_code = "en"
        self.referral_code = f"REF-{telegram_id}"
        self.role = "user"
        self.is_banned = False
        self.totp_enabled = False
        self.totp_secret = None
        self.is_premium = False
        self.premium_expires_at = None
        self.token_balance = 100
        self.total_tokens_purchased = 0
        self.total_tokens_spent = 0
        self.total_requests = 0
        self.last_active_at = datetime.now(UTC)
        self.last_login_at = None


class _FakeSession:
    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


@pytest.fixture
def fake_settings() -> _Settings:
    return _Settings()


@pytest.fixture
def stub_user() -> FakeUser:
    return FakeUser(id=42, telegram_id=42)


@pytest.fixture
def build_app(monkeypatch, fake_settings, stub_user):
    from app.api.v1 import compliance as compliance_module
    from app.auth import dependencies as deps
    from app.main import create_app
    from app.services import users as users_module

    store: dict[int, FakeUser] = {stub_user.telegram_id: stub_user}

    async def fake_upsert(session, *, telegram_user, super_admin_ids):
        tid = int(telegram_user["id"])
        existing = store.get(tid)
        if existing is None:
            new_user = FakeUser(id=tid, telegram_id=tid)
            store[tid] = new_user
            return new_user, True
        return existing, False

    async def fake_find_by_id(session, user_id):
        for u in store.values():
            if u.id == user_id:
                return u
        return None

    fake_session = _FakeSession()

    async def fake_get_session():
        yield fake_session

    monkeypatch.setattr(users_module, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(users_module, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(deps, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "get_session", fake_get_session)
    monkeypatch.setattr("app.core.config.get_settings", lambda: fake_settings)
    monkeypatch.setattr("app.auth.dependencies.get_settings", lambda: fake_settings)
    monkeypatch.setattr(compliance_module, "get_settings", lambda: fake_settings)

    app = create_app()

    from app.auth.dependencies import _settings_dep
    from app.core.database import get_session as real_get_session

    async def _yield_session():
        yield fake_session

    app.dependency_overrides[real_get_session] = _yield_session
    app.dependency_overrides[_settings_dep] = lambda: fake_settings

    return app, store, fake_settings


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


# ------------------------------------------------------------------- GET state


@pytest.mark.asyncio
async def test_get_returns_404_when_feature_disabled(build_app) -> None:
    app, _store, _settings = build_app
    init = _build_init_data()
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/me/age-verification",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "age_verification_disabled"


@pytest.mark.asyncio
async def test_get_returns_unverified_when_enabled(build_app) -> None:
    app, _store, settings = build_app
    settings.compliance_age_gate_enabled = True
    init = _build_init_data()
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/me/age-verification",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "enabled": True,
        "provider": "self_declared",
        "verified": False,
        "verified_at": None,
    }


# ------------------------------------------------------------------- POST stub


@pytest.mark.asyncio
async def test_post_returns_404_when_feature_disabled(build_app) -> None:
    app, _store, _settings = build_app
    init = _build_init_data()
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/me/age-verification",
            headers={"X-Telegram-Init-Data": init},
            json={"confirmed_18_plus": True},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "age_verification_disabled"


@pytest.mark.asyncio
async def test_post_self_declared_dev_marks_verified(build_app) -> None:
    app, _store, settings = build_app
    settings.compliance_age_gate_enabled = True
    init = _build_init_data()
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/me/age-verification",
            headers={"X-Telegram-Init-Data": init},
            json={"confirmed_18_plus": True},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enabled"] is True
    assert body["provider"] == "self_declared"
    assert body["verified"] is True
    assert body["verified_at"] is not None


@pytest.mark.asyncio
async def test_post_with_unimplemented_provider_returns_501(build_app) -> None:
    app, _store, settings = build_app
    settings.compliance_age_gate_enabled = True
    settings.compliance_age_gate_provider = "veriff"
    init = _build_init_data()
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/me/age-verification",
            headers={"X-Telegram-Init-Data": init},
            json={"confirmed_18_plus": True},
        )
    assert resp.status_code == 501
    assert resp.json()["detail"] == "age_verification_provider_not_integrated"


@pytest.mark.asyncio
async def test_post_self_declared_outside_dev_is_blocked(build_app) -> None:
    app, _store, settings = build_app
    settings.compliance_age_gate_enabled = True
    settings.app_env = "production"
    init = _build_init_data()
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/me/age-verification",
            headers={"X-Telegram-Init-Data": init},
            json={"confirmed_18_plus": True},
        )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "age_verification_self_declared_not_allowed"


@pytest.mark.asyncio
async def test_post_rejects_declined_confirmation(build_app) -> None:
    app, _store, settings = build_app
    settings.compliance_age_gate_enabled = True
    init = _build_init_data()
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/me/age-verification",
            headers={"X-Telegram-Init-Data": init},
            json={"confirmed_18_plus": False},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "age_verification_declined"


@pytest.mark.asyncio
async def test_post_rejects_provider_mismatch(build_app) -> None:
    app, _store, settings = build_app
    settings.compliance_age_gate_enabled = True
    settings.compliance_age_gate_provider = "self_declared"
    init = _build_init_data()
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/me/age-verification",
            headers={"X-Telegram-Init-Data": init},
            json={"confirmed_18_plus": True, "provider": "veriff"},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "age_verification_provider_mismatch"
