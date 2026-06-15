"""Integration tests for ``POST /api/v1/bot/webhook``.

We mock:

* the Telegram Bot API via ``httpx.MockTransport`` injected into our
  ``TelegramClient`` (so we can assert exactly what the bot tried to send);
* the DB session with an in-memory stub that records the user records that
  would have been written; and
* the user/registration services so the route exercises the dispatcher +
  handlers end-to-end without Postgres.

The shape of these tests mirrors ``test_auth_endpoints.py`` for consistency.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

WEBHOOK_PATH = "/api/v1/bot/webhook"


# --------------------------------------------------------------------- stubs


class _FakeSettings:
    app_name = "telegram-ai-agent-backend"
    app_env = "development"
    app_debug = True
    log_level = "INFO"
    log_format = "console"
    api_v1_prefix = "/api/v1"
    database_url = "postgresql+asyncpg://test/test"
    redis_url = "redis://localhost:6379/0"
    health_check_timeout = 2.0

    telegram_bot_token = "TESTBOT:secret"
    telegram_bot_username = "test_bot"
    telegram_api_base_url = "https://api.telegram.org"
    telegram_webhook_secret = "supersecret"
    telegram_mini_app_url = ""
    telegram_signup_bonus_tokens = 50
    telegram_update_idempotency_ttl_seconds = 604800
    telegram_init_data_max_age = 86400
    telegram_set_commands_on_startup = False

    admin_jwt_secret = "test"
    admin_jwt_algorithm = "HS256"
    admin_access_token_ttl = 60
    admin_refresh_token_ttl = 600
    admin_login_code_ttl = 60
    admin_login_code_length = 6
    admin_login_max_attempts = 5
    admin_super_telegram_ids = ""

    totp_issuer = "Test"

    @property
    def is_development(self) -> bool:
        return True

    @property
    def super_admin_ids(self) -> set[int]:
        return set()


@dataclass
class FakeUser:
    id: int
    telegram_id: int
    first_name: str | None = "Alice"
    username: str | None = "alice"
    last_name: str | None = None
    language_code: str | None = "en"
    token_balance: int = 0
    total_tokens_purchased: int = 0
    total_tokens_spent: int = 0
    total_requests: int = 0
    is_premium: bool = False
    referral_code: str = "ALICE123"
    referred_by: int | None = None
    is_banned: bool = False
    role: str = "user"


@dataclass
class _Store:
    by_telegram: dict[int, FakeUser] = field(default_factory=dict)
    by_referral: dict[str, FakeUser] = field(default_factory=dict)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    next_id: int = 1


@dataclass
class _SessionControls:
    commit_errors: list[Exception] = field(default_factory=list)
    commits: int = 0
    rollbacks: int = 0


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, *, ex: int, nx: bool) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        self.ttls[key] = ex
        return True

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if key in self.values:
                deleted += 1
                self.values.pop(key, None)
                self.ttls.pop(key, None)
        return deleted


@pytest.fixture
def store() -> _Store:
    return _Store()


@pytest.fixture
def fake_redis() -> _FakeRedis:
    return _FakeRedis()


@pytest.fixture
def captured_requests() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def session_controls() -> _SessionControls:
    return _SessionControls()


@pytest.fixture
def settings() -> _FakeSettings:
    return _FakeSettings()


@pytest.fixture
def build_app(monkeypatch, store, fake_redis, captured_requests, settings, session_controls):
    """Wire the FastAPI app with stubbed DB/Telegram so the webhook is callable."""
    from app.api.v1 import bot as bot_route
    from app.auth import dependencies as deps
    from app.bot import handlers as handlers_module
    from app.bot.client import TelegramClient
    from app.main import create_app
    from app.services import bot_users as bot_users_service
    from app.services import users as users_module
    from app.services.composio import MockComposioClient

    # --- DB stubs --------------------------------------------------------

    async def fake_find_user_by_telegram_id(_session, telegram_id):
        return store.by_telegram.get(int(telegram_id))

    async def fake_upsert(_session, *, telegram_user, super_admin_ids):
        tid = int(telegram_user["id"])
        existing = store.by_telegram.get(tid)
        if existing:
            existing.first_name = telegram_user.get("first_name", existing.first_name)
            existing.username = telegram_user.get("username", existing.username)
            return existing, False
        store.next_id += 1
        new_user = FakeUser(
            id=store.next_id,
            telegram_id=tid,
            first_name=telegram_user.get("first_name"),
            username=telegram_user.get("username"),
            language_code=telegram_user.get("language_code") or "en",
            referral_code=f"REF{tid}",
        )
        store.by_telegram[tid] = new_user
        store.by_referral[new_user.referral_code] = new_user
        return new_user, True

    async def fake_find_by_referral(_session, code):
        return store.by_referral.get(code)

    class _SessionStub:
        async def flush(self):
            return None

        async def commit(self):
            session_controls.commits += 1
            if session_controls.commit_errors:
                raise session_controls.commit_errors.pop(0)
            return None

        async def rollback(self):
            session_controls.rollbacks += 1
            return None

        def add(self, obj):  # noqa: ANN001 — duck-typed Transaction record
            tx = {
                "user_id": getattr(obj, "user_id", None),
                "type": getattr(obj, "transaction_type", None),
                "tokens": getattr(obj, "tokens_amount", None),
                "package": getattr(obj, "package_name", None),
            }
            store.transactions.append(tx)

        async def execute(self, *args, **kwargs):
            raise AssertionError("DB execute should be mocked, not called")

    async def fake_get_session():
        yield _SessionStub()

    monkeypatch.setattr(users_module, "find_user_by_telegram_id", fake_find_user_by_telegram_id)
    monkeypatch.setattr(users_module, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(handlers_module, "find_user_by_telegram_id", fake_find_user_by_telegram_id)
    monkeypatch.setattr(bot_users_service, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(bot_users_service, "_find_user_by_referral_code", fake_find_by_referral)

    # --- settings + bot client -------------------------------------------

    bot_route.reset_bot_client()
    # Capture the *original* dependency function before monkeypatch swaps the
    # attribute — ``Depends(get_bot_client)`` in the route binds at import time,
    # so the dependency_overrides key must match that original reference.
    original_get_bot_client = bot_route.get_bot_client

    async def telegram_handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(
            {
                "url": str(request.url),
                "body": json.loads(request.content.decode()),
            }
        )
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = httpx.MockTransport(telegram_handler)
    fake_http = httpx.AsyncClient(transport=transport)
    fake_client = TelegramClient(
        settings.telegram_bot_token,
        base_url=settings.telegram_api_base_url,
        http_client=fake_http,
    )

    monkeypatch.setattr(bot_route, "get_bot_client", lambda: fake_client)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings, raising=True)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)

    app = create_app()

    # FastAPI resolves these via Depends() at request time; override after creation.
    from app.api.v1.generate import get_composio_client as real_get_composio_client
    from app.auth.dependencies import _settings_dep
    from app.core.database import get_session as real_get_session

    app.dependency_overrides[real_get_session] = fake_get_session
    app.dependency_overrides[_settings_dep] = lambda: settings
    app.dependency_overrides[original_get_bot_client] = lambda: fake_client
    app.dependency_overrides[real_get_composio_client] = lambda: MockComposioClient()
    app.dependency_overrides[bot_route._redis_dep] = lambda: fake_redis

    yield app, store, captured_requests

    bot_route.reset_bot_client()


async def _client(app: Any) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _start_update(telegram_id: int, *, payload: str | None = None) -> dict[str, Any]:
    text = "/start"
    if payload:
        text = f"/start {payload}"
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "date": 1700000000,
            "chat": {"id": telegram_id, "type": "private"},
            "from": {
                "id": telegram_id,
                "is_bot": False,
                "first_name": "Alice",
                "username": "alice",
                "language_code": "en",
            },
            "text": text,
            "entities": [{"type": "bot_command", "offset": 0, "length": 6}],
        },
    }


# ------------------------------------------------------------------- tests


@pytest.mark.asyncio
async def test_webhook_rejects_missing_secret(build_app) -> None:
    app, _, _ = build_app
    async with await _client(app) as c:
        resp = await c.post(WEBHOOK_PATH, json=_start_update(1))
    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_webhook_secret"


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret(build_app) -> None:
    app, _, _ = build_app
    async with await _client(app) as c:
        resp = await c.post(
            WEBHOOK_PATH,
            json=_start_update(1),
            headers={"X-Telegram-Bot-Api-Secret-Token": "WRONG"},
        )
    assert resp.status_code == 401


def test_check_secret_uses_constant_time_compare(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import bot as bot_route

    compare_calls: list[tuple[str, str]] = []

    class _FakeHmac:
        @staticmethod
        def compare_digest(left: str, right: str) -> bool:
            compare_calls.append((left, right))
            return True

    monkeypatch.setattr(bot_route, "hmac", _FakeHmac, raising=False)

    bot_route._check_secret("supersecret", "supersecret")

    assert compare_calls == [("supersecret", "supersecret")]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"X-Telegram-Bot-Api-Secret-Token": "WRONG"},
    ],
)
@pytest.mark.asyncio
async def test_webhook_rejects_missing_or_wrong_secret_in_production(
    build_app,
    settings,
    headers: dict[str, str],
) -> None:
    settings.app_env = "production"
    settings.app_debug = False
    settings.telegram_webhook_secret = "prod-supersecret"

    app, _, _ = build_app
    async with await _client(app) as c:
        resp = await c.post(WEBHOOK_PATH, json=_start_update(1), headers=headers)

    assert resp.status_code == 401
    assert resp.json()["detail"] == "invalid_webhook_secret"


@pytest.mark.asyncio
async def test_webhook_start_creates_user_and_awards_bonus(build_app) -> None:
    app, store, captured = build_app
    async with await _client(app) as c:
        resp = await c.post(
            WEBHOOK_PATH,
            json=_start_update(4242),
            headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    user = store.by_telegram[4242]
    assert user.token_balance == 50

    bonus_tx = [tx for tx in store.transactions if tx["type"] == "bonus"]
    assert len(bonus_tx) == 1
    assert bonus_tx[0]["tokens"] == 50

    assert any("sendMessage" in r["url"] for r in captured)
    welcome = next(r for r in captured if "sendMessage" in r["url"])
    assert welcome["body"]["chat_id"] == 4242
    assert "Welcome" in welcome["body"]["text"]
    assert "50 tokens" in welcome["body"]["text"]


@pytest.mark.asyncio
async def test_webhook_start_does_not_re_award_bonus(build_app) -> None:
    app, store, captured = build_app
    headers = {"X-Telegram-Bot-Api-Secret-Token": "supersecret"}
    async with await _client(app) as c:
        await c.post(WEBHOOK_PATH, json=_start_update(33), headers=headers)
        await c.post(WEBHOOK_PATH, json=_start_update(33), headers=headers)

    assert store.by_telegram[33].token_balance == 50  # only credited once
    bonus_tx = [tx for tx in store.transactions if tx["type"] == "bonus"]
    assert len(bonus_tx) == 1


@pytest.mark.asyncio
async def test_webhook_short_circuits_duplicate_update_id(
    build_app, fake_redis, settings, monkeypatch
) -> None:
    app, _, _ = build_app

    from app.api.v1 import bot as bot_route

    dispatched: list[int] = []

    async def fake_dispatch(update: dict[str, Any], **_kwargs: Any) -> None:
        dispatched.append(int(update["update_id"]))

    monkeypatch.setattr(bot_route, "dispatch_update", fake_dispatch)

    headers = {"X-Telegram-Bot-Api-Secret-Token": "supersecret"}
    update = _start_update(33)
    async with await _client(app) as c:
        first = await c.post(WEBHOOK_PATH, json=update, headers=headers)
        second = await c.post(WEBHOOK_PATH, json=update, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert dispatched == [1]
    assert fake_redis.values == {"bot:webhook:update:1": "1"}
    assert fake_redis.ttls == {
        "bot:webhook:update:1": settings.telegram_update_idempotency_ttl_seconds
    }


@pytest.mark.asyncio
async def test_webhook_releases_update_id_claim_after_commit_failure(
    build_app, fake_redis, session_controls, monkeypatch
) -> None:
    app, _, _ = build_app

    from app.api.v1 import bot as bot_route

    dispatched: list[int] = []

    async def fake_dispatch(update: dict[str, Any], **_kwargs: Any) -> None:
        dispatched.append(int(update["update_id"]))

    monkeypatch.setattr(bot_route, "dispatch_update", fake_dispatch)
    session_controls.commit_errors.append(RuntimeError("database temporarily unavailable"))

    headers = {"X-Telegram-Bot-Api-Secret-Token": "supersecret"}
    update = _start_update(33)
    async with await _client(app) as c:
        first = await c.post(WEBHOOK_PATH, json=update, headers=headers)
        second = await c.post(WEBHOOK_PATH, json=update, headers=headers)

    assert first.status_code == 500
    assert second.status_code == 200
    assert dispatched == [1, 1]
    assert session_controls.commits == 2
    assert session_controls.rollbacks == 1
    assert fake_redis.values == {"bot:webhook:update:1": "1"}


@pytest.mark.asyncio
async def test_webhook_releases_update_id_claim_after_dispatch_failure(
    build_app, fake_redis, session_controls, monkeypatch
) -> None:
    app, _, _ = build_app

    from app.api.v1 import bot as bot_route

    dispatched: list[int] = []

    async def flaky_dispatch(update: dict[str, Any], **_kwargs: Any) -> None:
        if not dispatched:
            dispatched.append(int(update["update_id"]))
            raise RuntimeError("dispatcher temporarily unavailable")
        dispatched.append(int(update["update_id"]))

    monkeypatch.setattr(bot_route, "dispatch_update", flaky_dispatch)

    headers = {"X-Telegram-Bot-Api-Secret-Token": "supersecret"}
    update = _start_update(33)
    async with await _client(app) as c:
        first = await c.post(WEBHOOK_PATH, json=update, headers=headers)
        second = await c.post(WEBHOOK_PATH, json=update, headers=headers)

    assert first.status_code == 500
    assert second.status_code == 200
    assert dispatched == [1, 1]
    assert session_controls.commits == 1
    assert session_controls.rollbacks == 1
    assert fake_redis.values == {"bot:webhook:update:1": "1"}


@pytest.mark.asyncio
async def test_webhook_start_with_referral_links_inviter(build_app) -> None:
    app, store, captured = build_app
    headers = {"X-Telegram-Bot-Api-Secret-Token": "supersecret"}

    # Seed an existing inviter so the referral code resolves.
    inviter = FakeUser(id=1, telegram_id=1, referral_code="INV-CODE", username="inv")
    store.by_telegram[1] = inviter
    store.by_referral["INV-CODE"] = inviter

    async with await _client(app) as c:
        resp = await c.post(
            WEBHOOK_PATH,
            json=_start_update(77, payload="INV-CODE"),
            headers=headers,
        )
    assert resp.status_code == 200
    invitee = store.by_telegram[77]
    assert invitee.referred_by == 1


@pytest.mark.asyncio
async def test_webhook_help_lists_commands(build_app) -> None:
    app, _, captured = build_app
    update = _start_update(100)
    update["message"]["text"] = "/help"
    async with await _client(app) as c:
        resp = await c.post(
            WEBHOOK_PATH,
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
        )
    assert resp.status_code == 200
    body = next(r["body"] for r in captured if "sendMessage" in r["url"])
    text = body["text"]
    assert "/start" in text and "/balance" in text and "/buy" in text


@pytest.mark.asyncio
async def test_webhook_balance_for_unknown_user(build_app) -> None:
    app, _, captured = build_app
    update = _start_update(555)
    update["message"]["text"] = "/balance"
    async with await _client(app) as c:
        resp = await c.post(
            WEBHOOK_PATH,
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
        )
    assert resp.status_code == 200
    body = next(r["body"] for r in captured if "sendMessage" in r["url"])
    assert "/start" in body["text"]


@pytest.mark.asyncio
async def test_webhook_balance_for_known_user(build_app) -> None:
    app, store, captured = build_app
    user = FakeUser(id=10, telegram_id=10, token_balance=120, is_premium=True)
    store.by_telegram[10] = user
    update = _start_update(10)
    update["message"]["text"] = "/balance"
    async with await _client(app) as c:
        await c.post(
            WEBHOOK_PATH,
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
        )
    body = next(r["body"] for r in captured if "sendMessage" in r["url"])
    assert "120" in body["text"]
    assert "Premium" in body["text"]


@pytest.mark.asyncio
async def test_webhook_referral_returns_link_with_user_code(build_app) -> None:
    app, store, captured = build_app
    user = FakeUser(id=11, telegram_id=11, referral_code="MYCODE")
    store.by_telegram[11] = user
    update = _start_update(11)
    update["message"]["text"] = "/referral"
    async with await _client(app) as c:
        await c.post(
            WEBHOOK_PATH,
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
        )
    body = next(r["body"] for r in captured if "sendMessage" in r["url"])
    assert "MYCODE" in body["text"]
    assert "test_bot" in body["text"]


@pytest.mark.asyncio
async def test_webhook_callback_query_acked(build_app) -> None:
    app, store, captured = build_app
    user = FakeUser(id=12, telegram_id=12, token_balance=7)
    store.by_telegram[12] = user

    update = {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": 12, "first_name": "Alice"},
            "message": {
                "message_id": 1,
                "chat": {"id": 12, "type": "private"},
            },
            "data": "menu:balance",
        },
    }
    async with await _client(app) as c:
        resp = await c.post(
            WEBHOOK_PATH,
            json=update,
            headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
        )
    assert resp.status_code == 200
    assert any("answerCallbackQuery" in r["url"] for r in captured)
    assert any("sendMessage" in r["url"] for r in captured)


@pytest.mark.asyncio
async def test_webhook_swallows_telegram_api_error(build_app, monkeypatch) -> None:
    """When the Bot API errors mid-handler the webhook still returns 200."""
    app, _, _ = build_app

    from app.api.v1 import bot as bot_route
    from app.bot.client import TelegramApiError

    failing = AsyncMock(side_effect=TelegramApiError("sendMessage", "Forbidden"))
    bot_route.get_bot_client().send_message = failing  # type: ignore[assignment]

    async with await _client(app) as c:
        resp = await c.post(
            WEBHOOK_PATH,
            json=_start_update(13),
            headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_webhook_ignores_updates_without_message_or_callback(build_app) -> None:
    app, _, captured = build_app
    async with await _client(app) as c:
        resp = await c.post(
            WEBHOOK_PATH,
            json={"update_id": 99},
            headers={"X-Telegram-Bot-Api-Secret-Token": "supersecret"},
        )
    assert resp.status_code == 200
    assert captured == []
