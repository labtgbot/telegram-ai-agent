"""End-to-end tests for the Phase-2 referral system.

Covers the three layers that touch a referral:

1. ``app.services.bot_users.register_or_update_user`` — invalid code,
   self-referral, repeat ``/start`` (in-memory stubs, no DB).
2. ``app.services.payments.PaymentService.finalize_successful_payment`` —
   first purchase credits the inviter once and is idempotent on
   duplicate webhooks (PostgreSQL integration, skipped when
   ``DATABASE_URL`` is unset).
3. ``GET /api/v1/user/referral`` — response shape and link composition
   (ASGI + in-memory stubs).
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
from sqlalchemy import select

BOT_TOKEN = "1234567890:TEST-AAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
JWT_SECRET = "test-secret"


# =========================================================================
# Unit tests for register_or_update_user — pure in-memory, no DB.
# =========================================================================


class _MemoryUser:
    """Minimal duck-typed stand-in for :class:`app.models.user.User`."""

    def __init__(
        self,
        *,
        id: int,
        telegram_id: int,
        referral_code: str,
        is_banned: bool = False,
    ) -> None:
        self.id = id
        self.telegram_id = telegram_id
        self.username = f"u{telegram_id}"
        self.first_name = "User"
        self.last_name = None
        self.language_code = "en"
        self.referral_code = referral_code
        self.referred_by: int | None = None
        self.is_banned = is_banned
        self.role = "user"
        self.token_balance = 0
        self.total_tokens_purchased = 0
        self.total_tokens_spent = 0
        self.total_requests = 0
        self.last_active_at = datetime.now(UTC)
        self.last_login_at = None


class _MemoryStore:
    def __init__(self) -> None:
        self.by_telegram: dict[int, _MemoryUser] = {}
        self.by_referral: dict[str, _MemoryUser] = {}
        self.next_id = 100
        self.transactions: list[dict[str, Any]] = []

    def add(self, user: _MemoryUser) -> None:
        self.by_telegram[user.telegram_id] = user
        self.by_referral[user.referral_code] = user


class _MemorySession:
    """Stand-in for ``AsyncSession`` — flush/add only, no real I/O."""

    def __init__(self, store: _MemoryStore) -> None:
        self._store = store

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None

    def add(self, obj: Any) -> None:
        self._store.transactions.append(
            {
                "user_id": getattr(obj, "user_id", None),
                "type": getattr(obj, "transaction_type", None),
                "tokens": getattr(obj, "tokens_amount", None),
                "package": getattr(obj, "package_name", None),
            }
        )

    async def execute(self, *_args, **_kwargs):  # pragma: no cover
        raise AssertionError("DB execute should be patched, not called")


@pytest.fixture
def memory_store() -> _MemoryStore:
    return _MemoryStore()


@pytest.fixture
def patch_bot_users(monkeypatch, memory_store: _MemoryStore):
    """Stub ``upsert_telegram_user`` and the referral-code lookup."""
    from app.services import bot_users as bot_users_service
    from app.services import users as users_module

    async def fake_upsert(_session, *, telegram_user, super_admin_ids=None):
        tid = int(telegram_user["id"])
        existing = memory_store.by_telegram.get(tid)
        if existing is not None:
            return existing, False
        memory_store.next_id += 1
        new_user = _MemoryUser(
            id=memory_store.next_id,
            telegram_id=tid,
            referral_code=f"REF{tid}",
        )
        memory_store.add(new_user)
        return new_user, True

    async def fake_find_by_referral(_session, code):
        return memory_store.by_referral.get(code)

    monkeypatch.setattr(users_module, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(bot_users_service, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(
        bot_users_service, "_find_user_by_referral_code", fake_find_by_referral
    )
    return memory_store


@pytest.mark.asyncio
async def test_register_links_referrer_on_first_contact(
    memory_store, patch_bot_users
) -> None:
    from app.services.bot_users import register_or_update_user

    inviter = _MemoryUser(id=1, telegram_id=1, referral_code="INVCODE")
    memory_store.add(inviter)
    session = _MemorySession(memory_store)

    result = await register_or_update_user(
        session,
        telegram_user={"id": 2, "first_name": "Bob"},
        referral_payload="INVCODE",
        signup_bonus_tokens=0,
    )

    assert result.created is True
    assert result.referrer is inviter
    assert result.user.referred_by == inviter.id


@pytest.mark.asyncio
async def test_register_ignores_unknown_referral_code(
    memory_store, patch_bot_users
) -> None:
    from app.services.bot_users import register_or_update_user

    session = _MemorySession(memory_store)
    result = await register_or_update_user(
        session,
        telegram_user={"id": 3, "first_name": "Carol"},
        referral_payload="NO-SUCH-CODE",
        signup_bonus_tokens=0,
    )

    assert result.created is True
    assert result.referrer is None
    assert result.user.referred_by is None


@pytest.mark.asyncio
async def test_register_rejects_self_referral(
    memory_store, monkeypatch
) -> None:
    """A user who pastes their own code into ``/start`` must not link to themselves."""
    from app.services import bot_users as bot_users_service
    from app.services.bot_users import register_or_update_user

    self_user = _MemoryUser(id=4, telegram_id=4, referral_code="MINE")
    memory_store.add(self_user)
    session = _MemorySession(memory_store)

    # The pathological case: ``upsert`` reports the user as freshly created
    # *and* they typed their own code as the payload.  Simulated here by
    # returning ``(self_user, True)`` so the referral branch is taken.
    async def fake_upsert(_s, *, telegram_user, super_admin_ids=None):
        return self_user, True

    async def fake_find(_s, code):
        return memory_store.by_referral.get(code)

    monkeypatch.setattr(bot_users_service, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(
        bot_users_service, "_find_user_by_referral_code", fake_find
    )

    result = await register_or_update_user(
        session,
        telegram_user={"id": 4, "first_name": "Self"},
        referral_payload="MINE",
        signup_bonus_tokens=0,
    )

    assert result.created is True
    assert result.referrer is None
    assert result.user.referred_by is None


@pytest.mark.asyncio
async def test_register_skips_banned_referrer(
    memory_store, patch_bot_users
) -> None:
    from app.services.bot_users import register_or_update_user

    banned = _MemoryUser(
        id=5,
        telegram_id=5,
        referral_code="BANNED1",
        is_banned=True,
    )
    memory_store.add(banned)
    session = _MemorySession(memory_store)

    result = await register_or_update_user(
        session,
        telegram_user={"id": 6, "first_name": "Eve"},
        referral_payload="BANNED1",
        signup_bonus_tokens=0,
    )

    # ``register_or_update_user`` still resolves the referrer row so callers
    # can log it, but must not write ``referred_by`` for a banned account.
    assert result.user.referred_by is None
    assert result.bonus_credited == 0


@pytest.mark.asyncio
async def test_register_does_not_overwrite_existing_link(
    memory_store, patch_bot_users
) -> None:
    """A second ``/start <code>`` from the same user must keep referred_by intact."""
    from app.services.bot_users import register_or_update_user

    inviter_a = _MemoryUser(id=10, telegram_id=10, referral_code="FIRST")
    inviter_b = _MemoryUser(id=11, telegram_id=11, referral_code="SECOND")
    memory_store.add(inviter_a)
    memory_store.add(inviter_b)
    session = _MemorySession(memory_store)

    first = await register_or_update_user(
        session,
        telegram_user={"id": 12, "first_name": "Sam"},
        referral_payload="FIRST",
        signup_bonus_tokens=0,
    )
    assert first.user.referred_by == inviter_a.id

    second = await register_or_update_user(
        session,
        telegram_user={"id": 12, "first_name": "Sam"},
        referral_payload="SECOND",
        signup_bonus_tokens=0,
    )
    assert second.created is False
    assert second.user.referred_by == inviter_a.id  # unchanged


# =========================================================================
# DB integration: referral bonus is credited on the *first* purchase only.
# =========================================================================


from unittest.mock import AsyncMock  # noqa: E402

# Pre-warm ``app.bot`` so ``app.bot.__init__`` finishes loading before
# ``app.services.payments`` is imported here — without this priming, the
# direct ``from app.services.payments`` below races the import of
# ``app.bot.handlers`` (which itself imports from payments) and trips a
# circular import on ``InvoiceNotFoundError``.
from app.bot.client import TelegramApiError  # noqa: F401, E402
from app.models import Transaction, User  # noqa: E402
from app.services.payments import (  # noqa: E402
    DEFAULT_CURRENCY,
    REFERRAL_BONUS_PACKAGE,
    REFERRAL_BONUS_PREFIX,
    PaymentService,
)


def _fake_client() -> Any:
    client = AsyncMock()
    client.create_invoice_link = AsyncMock(return_value="https://t.me/$test")
    client.send_invoice = AsyncMock(return_value={"message_id": 1})
    client.answer_pre_checkout_query = AsyncMock(return_value=True)
    return client


async def _make_user(
    session,
    *,
    telegram_id: int,
    code: str,
    referred_by: int | None = None,
    balance: int = 0,
) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"u{telegram_id}",
        referral_code=code,
        token_balance=balance,
        referred_by=referred_by,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_first_purchase_credits_referrer_bonus(db_session):
    inviter = await _make_user(
        db_session, telegram_id=8_100_001, code="REF-INV-1"
    )
    invitee = await _make_user(
        db_session,
        telegram_id=8_100_002,
        code="REF-VEE-1",
        referred_by=inviter.id,
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=invitee.id, package_code="starter")

    result = await svc.finalize_successful_payment(
        telegram_user_id=invitee.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-ref-1",
    )
    assert result.tokens_credited == 500  # starter pack

    await db_session.refresh(inviter)
    assert inviter.token_balance == 100  # default referral bonus

    bonus_rows = (
        await db_session.execute(
            select(Transaction).where(
                Transaction.user_id == inviter.id,
                Transaction.transaction_type == "bonus",
                Transaction.package_name == REFERRAL_BONUS_PACKAGE,
            )
        )
    ).scalars().all()
    assert len(bonus_rows) == 1
    assert bonus_rows[0].tokens_amount == 100
    assert bonus_rows[0].payment_id == f"{REFERRAL_BONUS_PREFIX}{invitee.id}"
    assert bonus_rows[0].payment_status == "completed"


@pytest.mark.asyncio
async def test_second_purchase_does_not_credit_referrer_again(db_session):
    inviter = await _make_user(
        db_session, telegram_id=8_100_011, code="REF-INV-2"
    )
    invitee = await _make_user(
        db_session,
        telegram_id=8_100_012,
        code="REF-VEE-2",
        referred_by=inviter.id,
    )
    svc = PaymentService(db_session, client=_fake_client())

    # First purchase — should credit.
    inv1 = await svc.create_invoice(user_id=invitee.id, package_code="starter")
    await svc.finalize_successful_payment(
        telegram_user_id=invitee.telegram_id,
        payload=inv1.payload,
        total_amount=inv1.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-ref2-a",
    )
    await db_session.refresh(inviter)
    assert inviter.token_balance == 100

    # Second purchase — should NOT credit again.
    inv2 = await svc.create_invoice(user_id=invitee.id, package_code="basic")
    await svc.finalize_successful_payment(
        telegram_user_id=invitee.telegram_id,
        payload=inv2.payload,
        total_amount=inv2.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-ref2-b",
    )
    await db_session.refresh(inviter)
    assert inviter.token_balance == 100  # still just the one credit

    bonus_rows = (
        await db_session.execute(
            select(Transaction).where(
                Transaction.user_id == inviter.id,
                Transaction.transaction_type == "bonus",
                Transaction.package_name == REFERRAL_BONUS_PACKAGE,
            )
        )
    ).scalars().all()
    assert len(bonus_rows) == 1


@pytest.mark.asyncio
async def test_duplicate_webhook_does_not_double_credit_referrer(db_session):
    inviter = await _make_user(
        db_session, telegram_id=8_100_021, code="REF-INV-3"
    )
    invitee = await _make_user(
        db_session,
        telegram_id=8_100_022,
        code="REF-VEE-3",
        referred_by=inviter.id,
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=invitee.id, package_code="starter")
    charge_id = "charge-ref-dup"

    await svc.finalize_successful_payment(
        telegram_user_id=invitee.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id=charge_id,
    )
    await svc.finalize_successful_payment(
        telegram_user_id=invitee.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id=charge_id,
    )

    await db_session.refresh(inviter)
    assert inviter.token_balance == 100

    bonus_rows = (
        await db_session.execute(
            select(Transaction).where(
                Transaction.user_id == inviter.id,
                Transaction.transaction_type == "bonus",
                Transaction.package_name == REFERRAL_BONUS_PACKAGE,
            )
        )
    ).scalars().all()
    assert len(bonus_rows) == 1


@pytest.mark.asyncio
async def test_purchase_without_referrer_skips_bonus(db_session):
    solo = await _make_user(
        db_session, telegram_id=8_100_030, code="REF-SOLO-1"
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=solo.id, package_code="starter")

    await svc.finalize_successful_payment(
        telegram_user_id=solo.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-solo-1",
    )

    bonus_rows = (
        await db_session.execute(
            select(Transaction).where(
                Transaction.transaction_type == "bonus",
                Transaction.package_name == REFERRAL_BONUS_PACKAGE,
            )
        )
    ).scalars().all()
    assert bonus_rows == []


@pytest.mark.asyncio
async def test_banned_referrer_does_not_receive_bonus(db_session):
    inviter = await _make_user(
        db_session, telegram_id=8_100_041, code="REF-BAN-1"
    )
    inviter.is_banned = True
    await db_session.flush()

    invitee = await _make_user(
        db_session,
        telegram_id=8_100_042,
        code="REF-BAN-2",
        referred_by=inviter.id,
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=invitee.id, package_code="starter")

    await svc.finalize_successful_payment(
        telegram_user_id=invitee.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-banned",
    )

    await db_session.refresh(inviter)
    assert inviter.token_balance == 0
    bonus_rows = (
        await db_session.execute(
            select(Transaction).where(Transaction.user_id == inviter.id)
        )
    ).scalars().all()
    assert bonus_rows == []


# =========================================================================
# GET /api/v1/user/referral — endpoint shape and link composition.
# =========================================================================


class _ApiSettings:
    app_env = "development"
    app_debug = True
    telegram_bot_token = BOT_TOKEN
    telegram_bot_username = "test_bot"
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


class _ApiUser:
    def __init__(
        self,
        *,
        id: int,
        telegram_id: int,
        referral_code: str,
    ) -> None:
        self.id = id
        self.telegram_id = telegram_id
        self.username = "alice"
        self.first_name = "Alice"
        self.last_name = None
        self.language_code = "en"
        self.referral_code = referral_code
        self.role = "user"
        self.is_banned = False
        self.is_premium = False
        self.premium_expires_at = None
        self.token_balance = 0
        self.total_tokens_purchased = 0
        self.total_tokens_spent = 0
        self.total_requests = 0
        self.last_active_at = datetime.now(UTC)
        self.last_login_at = None


@pytest.fixture
def referral_app(monkeypatch):
    """Wire the FastAPI app for ``GET /user/referral`` with stubbed dependencies."""
    from app.api.v1 import user as user_module
    from app.auth import dependencies as deps
    from app.main import create_app
    from app.services import users as users_module

    settings = _ApiSettings()
    user = _ApiUser(id=42, telegram_id=42, referral_code="ABCD1234")
    store: dict[int, _ApiUser] = {user.telegram_id: user}
    counters: dict[str, int] = {"referrals_count": 3, "bonus_earned": 250}

    async def fake_upsert(session, *, telegram_user, super_admin_ids):
        tid = int(telegram_user["id"])
        existing = store.get(tid)
        if existing is None:
            new_user = _ApiUser(
                id=tid,
                telegram_id=tid,
                referral_code=f"REF-{tid}",
            )
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

    async def fake_count(_session, _uid):
        return counters["referrals_count"]

    async def fake_sum(_session, _uid):
        return counters["bonus_earned"]

    monkeypatch.setattr(users_module, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(users_module, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(deps, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "get_session", fake_get_session)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: settings, raising=True
    )
    # ``user.py`` imports ``get_settings`` at module load time, so the name
    # resolves against its own module namespace — patch that binding too.
    monkeypatch.setattr(user_module, "get_settings", lambda: settings)
    monkeypatch.setattr(user_module, "_count_referrals", fake_count)
    monkeypatch.setattr(user_module, "_sum_referral_bonus", fake_sum)

    app = create_app()
    from app.auth.dependencies import _settings_dep
    from app.core.database import get_session as real_get_session

    async def _yield_none():
        yield None

    app.dependency_overrides[real_get_session] = _yield_none
    app.dependency_overrides[_settings_dep] = lambda: settings

    return app, store, counters


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


@pytest.mark.asyncio
async def test_referral_endpoint_returns_link_and_counts(referral_app) -> None:
    app, _store, counters = referral_app
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/referral",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["referral_code"] == "ABCD1234"
    assert body["referrals_count"] == counters["referrals_count"]
    assert body["bonus_tokens_earned"] == counters["bonus_earned"]
    assert body["referral_link"] == "https://t.me/test_bot?start=ABCD1234"


@pytest.mark.asyncio
async def test_referral_endpoint_falls_back_when_username_missing(
    referral_app, monkeypatch
) -> None:
    app, _store, _counters = referral_app

    class _NoUsername(_ApiSettings):
        telegram_bot_username = ""

    no_username = _NoUsername()
    monkeypatch.setattr(
        "app.core.config.get_settings", lambda: no_username, raising=True
    )
    from app.api.v1 import user as user_module
    monkeypatch.setattr(user_module, "get_settings", lambda: no_username)

    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/referral",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["referral_link"] == "start=REF:ABCD1234"


@pytest.mark.asyncio
async def test_referral_endpoint_requires_init_data(referral_app) -> None:
    app, *_ = referral_app
    async with await _client(app) as c:
        resp = await c.get("/api/v1/user/referral")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "missing_init_data"
