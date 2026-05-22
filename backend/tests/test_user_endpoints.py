"""Endpoint-level tests for ``/api/v1/user/*``.

DB and auth dependencies are stubbed with in-memory fakes so the suite
runs without external services.  The shape of the fixture follows
``test_auth_endpoints.py`` for consistency.

Covered routes:

* ``GET /api/v1/user/balance``
* ``GET /api/v1/user/usage-history``
* ``GET /api/v1/user/transactions`` (Mini App balance page history)
* ``GET /api/v1/user/referral`` (Mini App referral link)
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
    telegram_bot_username = "test_ai_bot"
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
        id: int,
        telegram_id: int,
        token_balance: int = 0,
        is_premium: bool = False,
        premium_expires_at: datetime | None = None,
    ) -> None:
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
        self.is_premium = is_premium
        self.premium_expires_at = premium_expires_at
        self.token_balance = token_balance
        self.total_tokens_purchased = 0
        self.total_tokens_spent = 0
        self.total_requests = 0
        self.last_active_at = datetime.now(UTC)
        self.last_login_at = None


class FakeUsageLog:
    def __init__(
        self,
        *,
        id: int,
        user_id: int,
        service_type: str,
        tokens_consumed: int,
        response_status: str | None = "ok",
        processing_time_ms: int | None = None,
        request_params: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.user_id = user_id
        self.service_type = service_type
        self.tokens_consumed = tokens_consumed
        self.response_status = response_status
        self.processing_time_ms = processing_time_ms
        self.request_params = request_params or {}
        self.created_at = created_at or datetime.now(UTC)


class _UsageHistoryPageStub:
    def __init__(
        self,
        items: list[FakeUsageLog],
        total: int,
        page: int,
        limit: int,
    ) -> None:
        self.items = items
        self.total = total
        self.page = page
        self.limit = limit
        self.has_more = (page * limit) < total


class FakeTransaction:
    """In-memory stand-in for :class:`app.models.transaction.Transaction`.

    Mirrors only the fields the ``/user/transactions`` endpoint reads.
    """

    def __init__(
        self,
        *,
        id: int,
        user_id: int,
        transaction_type: str,
        tokens_amount: int,
        stars_amount: int | None = None,
        package_name: str | None = None,
        payment_status: str | None = None,
        payment_method: str | None = None,
        created_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        self.id = id
        self.user_id = user_id
        self.transaction_type = transaction_type
        self.tokens_amount = tokens_amount
        self.stars_amount = stars_amount
        self.package_name = package_name
        self.payment_status = payment_status
        self.payment_method = payment_method
        self.created_at = created_at or datetime.now(UTC)
        self.completed_at = completed_at


@pytest.fixture
def fake_settings() -> _Settings:
    return _Settings()


@pytest.fixture
def stub_user() -> FakeUser:
    return FakeUser(id=42, telegram_id=42, token_balance=250)


@pytest.fixture
def usage_logs() -> list[FakeUsageLog]:
    return [
        FakeUsageLog(
            id=i,
            user_id=42,
            service_type=f"svc_{i}",
            tokens_consumed=10 * i,
        )
        for i in range(1, 6)
    ]


@pytest.fixture
def fake_transactions() -> list[FakeTransaction]:
    """A small ledger covering every transaction type the API exposes."""
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    return [
        FakeTransaction(
            id=1,
            user_id=42,
            transaction_type="purchase",
            tokens_amount=500,
            stars_amount=250,
            package_name="starter",
            payment_status="completed",
            payment_method="telegram_stars",
            created_at=base,
            completed_at=base,
        ),
        FakeTransaction(
            id=2,
            user_id=42,
            transaction_type="bonus",
            tokens_amount=50,
            package_name="daily_bonus",
            created_at=base.replace(day=2),
        ),
        FakeTransaction(
            id=3,
            user_id=42,
            transaction_type="spend",
            tokens_amount=-20,
            created_at=base.replace(day=3),
        ),
        FakeTransaction(
            id=4,
            user_id=42,
            transaction_type="refund",
            tokens_amount=20,
            created_at=base.replace(day=4),
        ),
        FakeTransaction(
            id=5,
            user_id=42,
            transaction_type="manual_bonus",
            tokens_amount=100,
            created_at=base.replace(day=5),
        ),
    ]


@pytest.fixture
def build_app(monkeypatch, fake_settings, stub_user, usage_logs, fake_transactions):
    """Return an app with all DB and dependency surfaces stubbed in memory."""
    from app.api.v1 import user as user_module
    from app.auth import dependencies as deps
    from app.main import create_app
    from app.services import users as users_module

    store: dict[int, FakeUser] = {stub_user.telegram_id: stub_user}
    daily_bonus_cooldown: dict[int, bool] = {}

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
        yield None

    monkeypatch.setattr(users_module, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(users_module, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(deps, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "get_session", fake_get_session)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: fake_settings, raising=True
    )
    monkeypatch.setattr("app.auth.dependencies.get_settings", lambda: fake_settings)
    # ``user.py`` imports ``get_settings`` at module load time, so we need to
    # rebind the name on the local module as well — otherwise routes still
    # see the original implementation that reads from the real environment.
    monkeypatch.setattr(user_module, "get_settings", lambda: fake_settings)

    # Patch the TokenService to a stub that pulls from the in-memory store.
    class _FakeService:
        def __init__(self, session, balance_cache=None):
            self.session = session
            self.balance_cache = balance_cache

        async def get_balance(self, user_id: int) -> int:
            for u in store.values():
                if u.id == user_id:
                    return int(u.token_balance)
            from app.services.token_service import UserNotFoundError

            raise UserNotFoundError(f"user {user_id}")

        async def usage_history(self, user_id: int, *, page: int = 1, limit: int = 20):
            page = max(int(page or 1), 1)
            limit = max(min(int(limit or 20), 100), 1)
            items = [log for log in usage_logs if log.user_id == user_id]
            total = len(items)
            offset = (page - 1) * limit
            return _UsageHistoryPageStub(
                items=items[offset : offset + limit],
                total=total,
                page=page,
                limit=limit,
            )

    monkeypatch.setattr(user_module, "TokenService", _FakeService)

    # Patch the daily-bonus probe so we don't need a Transaction table query.
    async def fake_daily_bonus_available(session, redis, user_id: int) -> bool:
        return not daily_bonus_cooldown.get(user_id, False)

    monkeypatch.setattr(
        user_module, "_daily_bonus_available", fake_daily_bonus_available
    )

    # Patch the transactions query so the endpoint can be tested without a DB.
    async def fake_list_transactions(
        session, *, user_id, page, limit, transaction_type
    ):
        rows = [t for t in fake_transactions if t.user_id == user_id]
        if transaction_type and transaction_type in {
            "purchase",
            "spend",
            "bonus",
            "refund",
            "manual_bonus",
        }:
            rows = [t for t in rows if t.transaction_type == transaction_type]
        rows_sorted = sorted(
            rows, key=lambda t: (t.created_at, t.id), reverse=True
        )
        total = len(rows_sorted)
        offset = (page - 1) * limit
        page_rows = rows_sorted[offset : offset + limit]
        return user_module._TransactionsPage(
            items=page_rows, total=total, page=page, limit=limit
        )

    monkeypatch.setattr(
        user_module, "_list_transactions", fake_list_transactions
    )

    # Patch referral counters so /user/referral doesn't need a DB.
    async def fake_count_referrals(session, user_id: int) -> int:
        return 0

    async def fake_sum_referral_bonus(session, user_id: int) -> int:
        return 0

    monkeypatch.setattr(user_module, "_count_referrals", fake_count_referrals)
    monkeypatch.setattr(
        user_module, "_sum_referral_bonus", fake_sum_referral_bonus
    )

    app = create_app()

    from app.auth.dependencies import _settings_dep
    from app.core.database import get_session as real_get_session

    async def _yield_none():
        yield None

    app.dependency_overrides[real_get_session] = _yield_none
    app.dependency_overrides[_settings_dep] = lambda: fake_settings
    app.dependency_overrides[user_module._redis_dep] = lambda: None

    return app, store, daily_bonus_cooldown, usage_logs, fake_transactions


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


# -------------------------------------------------------------- /user/balance


@pytest.mark.asyncio
async def test_balance_returns_current_state(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/balance",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_balance"] == 250
    assert body["is_premium"] is False
    assert body["premium_expires_at"] is None
    assert body["daily_bonus_available"] is True


@pytest.mark.asyncio
async def test_balance_reflects_daily_bonus_cooldown(build_app) -> None:
    app, _store, cooldown, *_ = build_app
    cooldown[42] = True
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/balance",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200
    assert resp.json()["daily_bonus_available"] is False


@pytest.mark.asyncio
async def test_balance_for_premium_user_returns_expires_at(build_app) -> None:
    app, store, *_ = build_app
    expires = datetime(2026, 12, 31, tzinfo=UTC)
    store[42] = FakeUser(
        id=42,
        telegram_id=42,
        token_balance=1_000,
        is_premium=True,
        premium_expires_at=expires,
    )
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/balance",
            headers={"X-Telegram-Init-Data": init},
        )
    body = resp.json()
    assert body["token_balance"] == 1_000
    assert body["is_premium"] is True
    assert body["premium_expires_at"].startswith("2026-12-31")


@pytest.mark.asyncio
async def test_balance_rejects_missing_init_data(build_app) -> None:
    app, *_ = build_app
    async with await _client(app) as c:
        resp = await c.get("/api/v1/user/balance")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"


@pytest.mark.asyncio
async def test_balance_rejects_tampered_init_data(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data().replace("Alice", "Mallory")
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/balance",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_init_data"


# -------------------------------------------------------- /user/usage-history


@pytest.mark.asyncio
async def test_usage_history_default_page(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/usage-history",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["limit"] == 20
    assert body["has_more"] is False
    assert len(body["items"]) == 5
    assert body["items"][0]["service_type"]
    assert body["items"][0]["tokens_consumed"] >= 0


@pytest.mark.asyncio
async def test_usage_history_pagination_returns_partial(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/usage-history?page=1&limit=2",
            headers={"X-Telegram-Init-Data": init},
        )
    body = resp.json()
    assert resp.status_code == 200
    assert body["limit"] == 2
    assert len(body["items"]) == 2
    assert body["has_more"] is True


@pytest.mark.asyncio
async def test_usage_history_rejects_invalid_pagination_params(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp_zero = await c.get(
            "/api/v1/user/usage-history?page=0",
            headers={"X-Telegram-Init-Data": init},
        )
        resp_big_limit = await c.get(
            "/api/v1/user/usage-history?limit=1000",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp_zero.status_code == 422
    assert resp_big_limit.status_code == 422


@pytest.mark.asyncio
async def test_usage_history_requires_init_data(build_app) -> None:
    app, *_ = build_app
    async with await _client(app) as c:
        resp = await c.get("/api/v1/user/usage-history")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"


# ---------------------------------------------------------- /user/transactions


@pytest.mark.asyncio
async def test_transactions_default_page_returns_all(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/transactions",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["limit"] == 20
    assert body["has_more"] is False
    assert len(body["items"]) == 5
    # Newest first (May 5 → May 1).
    assert body["items"][0]["id"] == 5
    assert body["items"][-1]["id"] == 1
    assert {item["transaction_type"] for item in body["items"]} == {
        "purchase",
        "spend",
        "bonus",
        "refund",
        "manual_bonus",
    }


@pytest.mark.asyncio
async def test_transactions_returns_full_purchase_shape(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/transactions?type=purchase",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    purchase = body["items"][0]
    assert purchase["transaction_type"] == "purchase"
    assert purchase["tokens_amount"] == 500
    assert purchase["stars_amount"] == 250
    assert purchase["package_name"] == "starter"
    assert purchase["payment_status"] == "completed"
    assert purchase["payment_method"] == "telegram_stars"
    assert purchase["completed_at"] is not None


@pytest.mark.asyncio
async def test_transactions_filter_by_type(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/transactions?type=bonus",
            headers={"X-Telegram-Init-Data": init},
        )
    body = resp.json()
    assert resp.status_code == 200
    assert body["total"] == 1
    assert body["items"][0]["transaction_type"] == "bonus"
    assert body["items"][0]["package_name"] == "daily_bonus"


@pytest.mark.asyncio
async def test_transactions_unknown_type_is_silently_ignored(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/transactions?type=ghost",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200
    # Unknown filter is dropped -> all 5 are returned.
    assert resp.json()["total"] == 5


@pytest.mark.asyncio
async def test_transactions_pagination_marks_has_more(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/transactions?page=1&limit=2",
            headers={"X-Telegram-Init-Data": init},
        )
    body = resp.json()
    assert resp.status_code == 200
    assert body["page"] == 1
    assert body["limit"] == 2
    assert body["total"] == 5
    assert body["has_more"] is True
    assert [item["id"] for item in body["items"]] == [5, 4]

    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/transactions?page=3&limit=2",
            headers={"X-Telegram-Init-Data": init},
        )
    body = resp.json()
    assert resp.status_code == 200
    assert [item["id"] for item in body["items"]] == [1]
    assert body["has_more"] is False


@pytest.mark.asyncio
async def test_transactions_rejects_invalid_pagination(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp_zero = await c.get(
            "/api/v1/user/transactions?page=0",
            headers={"X-Telegram-Init-Data": init},
        )
        resp_big = await c.get(
            "/api/v1/user/transactions?limit=1000",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp_zero.status_code == 422
    assert resp_big.status_code == 422


@pytest.mark.asyncio
async def test_transactions_requires_init_data(build_app) -> None:
    app, *_ = build_app
    async with await _client(app) as c:
        resp = await c.get("/api/v1/user/transactions")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"


@pytest.mark.asyncio
async def test_transactions_rejects_tampered_init_data(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data().replace("Alice", "Mallory")
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/transactions",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_init_data"


# --------------------------------------------------------------- /user/referral


@pytest.mark.asyncio
async def test_referral_builds_https_link_when_bot_username_set(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/referral",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["referral_code"] == "REF-42"
    assert body["referral_link"] == "https://t.me/test_ai_bot?start=REF-42"
    assert body["referrals_count"] == 0
    assert body["bonus_tokens_earned"] == 0


@pytest.mark.asyncio
async def test_referral_falls_back_when_bot_username_blank(
    build_app, fake_settings, monkeypatch
) -> None:
    fake_settings.telegram_bot_username = ""
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: fake_settings, raising=True
    )
    from app.api.v1 import user as user_module

    monkeypatch.setattr(user_module, "get_settings", lambda: fake_settings)
    app, *_ = build_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/referral",
            headers={"X-Telegram-Init-Data": init},
        )
    body = resp.json()
    assert resp.status_code == 200
    assert body["referral_link"] == "start=REF:REF-42"


@pytest.mark.asyncio
async def test_referral_requires_init_data(build_app) -> None:
    app, *_ = build_app
    async with await _client(app) as c:
        resp = await c.get("/api/v1/user/referral")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"


@pytest.mark.asyncio
async def test_referral_rejects_tampered_init_data(build_app) -> None:
    app, *_ = build_app
    init = _build_init_data().replace("Alice", "Mallory")
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/referral",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_init_data"
