"""Endpoint-level tests for the GDPR data-export / account-deletion endpoints
on ``/api/v1/user/*``.

The handlers wire up two services (``app.services.data_export`` and
``app.services.account_deletion``) that hit Postgres. We stub the services
in-place so the suite runs without a database.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta
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

    @property
    def is_development(self) -> bool:
        return True

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


class _FakeDeletionRequest:
    def __init__(
        self,
        *,
        request_id: int,
        user_id: int,
        scheduled_for: datetime,
        requested_at: datetime,
    ) -> None:
        self.id = request_id
        self.user_id = user_id
        self.scheduled_for = scheduled_for
        self.requested_at = requested_at
        self.status = "pending"


class _FakeSession:
    """Stub session that records commit/rollback calls."""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.commit_should_fail = False

    async def commit(self) -> None:
        if self.commit_should_fail:
            raise RuntimeError("simulated commit failure")
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


@pytest.fixture
def fake_settings() -> _Settings:
    return _Settings()


@pytest.fixture
def stub_user() -> FakeUser:
    return FakeUser(id=42, telegram_id=42)


@pytest.fixture
def build_app(monkeypatch, fake_settings, stub_user):
    """Build the app with auth and service deps stubbed."""
    from app.api.v1 import user as user_module
    from app.auth import dependencies as deps
    from app.main import create_app
    from app.services import account_deletion as account_deletion_service
    from app.services import data_export as data_export_service
    from app.services import users as users_module

    store: dict[int, FakeUser] = {stub_user.telegram_id: stub_user}
    fake_session = _FakeSession()
    # Track of "fake DB state" so tests can drive scenarios.
    state: dict[str, Any] = {
        "pending_request": None,  # type: _FakeDeletionRequest | None
        "export_built": 0,
        "request_calls": [],
        "cancel_calls": [],
        "session": fake_session,
    }

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

    async def fake_get_session():
        yield fake_session

    monkeypatch.setattr(users_module, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(users_module, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(deps, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "get_session", fake_get_session)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: fake_settings, raising=True
    )
    monkeypatch.setattr("app.auth.dependencies.get_settings", lambda: fake_settings)

    # ----- data_export stub ----------------------------------------------
    async def fake_build_export(session, *, user, max_chat_messages=10_000):
        state["export_built"] += 1
        return data_export_service.UserDataExport(
            schema_version=data_export_service.EXPORT_SCHEMA_VERSION,
            generated_at=datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC),
            user={"id": user.id, "telegram_id": user.telegram_id},
            transactions=[{"id": 1, "tokens_amount": 100}],
            subscriptions=[],
            chat_threads=[],
            chat_messages=[],
            daily_bonus_claims=[],
            referrals_summary={"count": 0},
            notes=[],
        )

    monkeypatch.setattr(user_module, "build_user_data_export", fake_build_export)

    # ----- account_deletion stubs ----------------------------------------
    async def fake_request_account_deletion(
        session,
        *,
        user,
        now=None,
        grace_period_days=30,
        requested_via=None,
        reason=None,
    ):
        state["request_calls"].append(
            {"user_id": user.id, "via": requested_via, "reason": reason}
        )
        if state["pending_request"] is not None:
            raise account_deletion_service.DeletionAlreadyPendingError(
                state["pending_request"]
            )
        now_utc = now or datetime.now(UTC)
        scheduled = now_utc + timedelta(days=grace_period_days)
        record = _FakeDeletionRequest(
            request_id=99,
            user_id=user.id,
            scheduled_for=scheduled,
            requested_at=now_utc,
        )
        state["pending_request"] = record
        return account_deletion_service.DeletionRequestResult(
            request_id=record.id,
            status=record.status,
            scheduled_for=record.scheduled_for,
            requested_at=record.requested_at,
        )

    async def fake_cancel_account_deletion(session, *, user, now=None):
        state["cancel_calls"].append(user.id)
        record = state["pending_request"]
        if record is None:
            raise account_deletion_service.NoPendingDeletionError(
                "no_pending_deletion"
            )
        state["pending_request"] = None
        return account_deletion_service.DeletionStatusSnapshot(
            pending=False,
            request_id=record.id,
            scheduled_for=record.scheduled_for,
            requested_at=record.requested_at,
        )

    async def fake_get_deletion_status(session, user_id):
        record = state["pending_request"]
        if record is None or record.user_id != user_id:
            return account_deletion_service.DeletionStatusSnapshot(
                pending=False,
                request_id=None,
                scheduled_for=None,
                requested_at=None,
            )
        return account_deletion_service.DeletionStatusSnapshot(
            pending=True,
            request_id=record.id,
            scheduled_for=record.scheduled_for,
            requested_at=record.requested_at,
        )

    monkeypatch.setattr(
        user_module, "request_account_deletion", fake_request_account_deletion
    )
    monkeypatch.setattr(
        user_module, "cancel_account_deletion", fake_cancel_account_deletion
    )
    monkeypatch.setattr(user_module, "get_deletion_status", fake_get_deletion_status)

    app = create_app()

    from app.auth.dependencies import _settings_dep
    from app.core.database import get_session as real_get_session

    async def _yield_session():
        yield fake_session

    app.dependency_overrides[real_get_session] = _yield_session
    app.dependency_overrides[_settings_dep] = lambda: fake_settings
    app.dependency_overrides[user_module._redis_dep] = lambda: None

    return app, store, state


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


# ----------------------------------------------------------------- /me/export


@pytest.mark.asyncio
async def test_export_returns_user_payload(build_app) -> None:
    app, _store, state = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/me/export",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == "1.0"
    assert body["user"]["id"] == 42
    assert body["transactions"][0]["id"] == 1
    assert body["referrals_summary"] == {"count": 0}
    assert body["notes"] == []
    assert state["export_built"] == 1


@pytest.mark.asyncio
async def test_export_rejects_missing_init_data(build_app) -> None:
    app, *_ = build_app
    async with await _client(app) as c:
        resp = await c.get("/api/v1/user/me/export")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"


# -------------------------------------------------------- /me/deletion-status


@pytest.mark.asyncio
async def test_deletion_status_no_pending(build_app) -> None:
    app, _store, _state = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/me/deletion-status",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {
        "pending": False,
        "request_id": None,
        "requested_at": None,
        "scheduled_for": None,
    }


@pytest.mark.asyncio
async def test_deletion_status_returns_pending_window(build_app) -> None:
    app, _store, state = build_app
    requested = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    state["pending_request"] = _FakeDeletionRequest(
        request_id=7,
        user_id=42,
        scheduled_for=requested + timedelta(days=30),
        requested_at=requested,
    )
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/me/deletion-status",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["pending"] is True
    assert body["request_id"] == 7
    assert body["requested_at"].startswith("2026-05-16")
    assert body["scheduled_for"].startswith("2026-06-15")


# --------------------------------------------------------------------- /me DELETE


@pytest.mark.asyncio
async def test_delete_account_schedules_grace_period(build_app) -> None:
    app, _store, state = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.delete(
            "/api/v1/user/me",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["request_id"] == 99
    assert body["status"] == "pending"
    assert body["detail"] == "deletion_scheduled"
    # FastAPI/pydantic serialises tz-aware datetimes with either ``Z`` or
    # ``+00:00`` depending on version — both are valid ISO-8601 UTC markers.
    assert body["scheduled_for"].endswith(("Z", "+00:00"))
    assert state["pending_request"] is not None
    assert state["request_calls"][0]["via"] == "mini_app"
    assert state["session"].commits == 1


@pytest.mark.asyncio
async def test_delete_account_conflict_when_pending(build_app) -> None:
    app, _store, state = build_app
    requested = datetime(2026, 5, 16, tzinfo=UTC)
    state["pending_request"] = _FakeDeletionRequest(
        request_id=5,
        user_id=42,
        scheduled_for=requested + timedelta(days=30),
        requested_at=requested,
    )
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.delete(
            "/api/v1/user/me",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "deletion_already_pending"
    assert detail["request_id"] == 5
    assert detail["scheduled_for"].startswith("2026-06-15")


@pytest.mark.asyncio
async def test_delete_account_rejects_missing_init_data(build_app) -> None:
    app, *_ = build_app
    async with await _client(app) as c:
        resp = await c.delete("/api/v1/user/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"


# ------------------------------------------------------------ /me/cancel-deletion


@pytest.mark.asyncio
async def test_cancel_deletion_clears_pending(build_app) -> None:
    app, _store, state = build_app
    state["pending_request"] = _FakeDeletionRequest(
        request_id=11,
        user_id=42,
        scheduled_for=datetime(2026, 6, 15, tzinfo=UTC),
        requested_at=datetime(2026, 5, 16, tzinfo=UTC),
    )
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/me/cancel-deletion",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"cancelled": True, "request_id": 11}
    assert state["pending_request"] is None


@pytest.mark.asyncio
async def test_cancel_deletion_returns_404_when_nothing_pending(build_app) -> None:
    app, _store, _state = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/me/cancel-deletion",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "no_pending_deletion"
