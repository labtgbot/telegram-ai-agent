"""End-to-end tests for the Phase-2 daily-bonus & streak loop (issue #22).

Covers four layers:

1. Pure helpers (``_streak_day_for``, ``_RuntimeConfig.amount_for_streak``,
   ``_payment_id``) — no IO at all.
2. Service against a real DB (``DailyBonusService.claim`` / ``.status``) —
   exercises the ledger row, UNIQUE constraint, ``TokenService.add`` and
   the AdminSetting override.  Skipped when ``DATABASE_URL`` is unset.
3. Streak progression and reset across UTC-day boundaries (DB-backed,
   driven by ``now=`` injection).
4. FastAPI endpoints (``GET`` + ``POST`` ``/api/v1/user/daily-bonus``)
   with in-memory stubs — verifies status shape, 200/409/403 codes and
   that the cooldown window is reported back to the client.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from typing import Any
from urllib.parse import urlencode

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

BOT_TOKEN = "1234567890:TEST-AAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
JWT_SECRET = "test-secret"


# =========================================================================
# Pure helpers — no DB, no Redis, no settings.
# =========================================================================


def test_runtime_config_caps_amount_at_last_value() -> None:
    from app.services.daily_bonus import _RuntimeConfig

    cfg = _RuntimeConfig(enabled=True, amounts=(10, 12, 15, 20))
    assert cfg.amount_for_streak(1) == 10
    assert cfg.amount_for_streak(2) == 12
    assert cfg.amount_for_streak(4) == 20
    assert cfg.amount_for_streak(5) == 20  # cap
    assert cfg.amount_for_streak(99) == 20  # still capped


def test_runtime_config_handles_single_amount() -> None:
    from app.services.daily_bonus import _RuntimeConfig

    cfg = _RuntimeConfig(enabled=True, amounts=(7,))
    assert cfg.amount_for_streak(1) == 7
    assert cfg.amount_for_streak(50) == 7


def test_streak_day_continues_on_consecutive_utc_dates() -> None:
    from app.services.daily_bonus import _LatestClaim, _streak_day_for

    yesterday = date(2026, 5, 15)
    latest = _LatestClaim(claim_date=yesterday, streak_day=3)
    assert _streak_day_for(today=date(2026, 5, 16), latest=latest) == 4


def test_streak_day_resets_after_gap() -> None:
    from app.services.daily_bonus import _LatestClaim, _streak_day_for

    latest = _LatestClaim(claim_date=date(2026, 5, 10), streak_day=4)
    assert _streak_day_for(today=date(2026, 5, 16), latest=latest) == 1


def test_streak_day_starts_at_one_when_no_history() -> None:
    from app.services.daily_bonus import _streak_day_for

    assert _streak_day_for(today=date(2026, 5, 16), latest=None) == 1


def test_payment_id_is_stable_per_user_and_date() -> None:
    from app.services.daily_bonus import _payment_id

    pid = _payment_id(42, date(2026, 5, 16))
    assert pid == "daily_bonus:user:42:date:2026-05-16"
    # Same inputs → same id (idempotency contract).
    assert _payment_id(42, date(2026, 5, 16)) == pid
    # Different date → different id.
    assert _payment_id(42, date(2026, 5, 17)) != pid


def test_coerce_amounts_rejects_zero_and_negative() -> None:
    from app.services.daily_bonus import _coerce_amounts

    assert _coerce_amounts([10, 12, 15]) == (10, 12, 15)
    assert _coerce_amounts("5,10,20") == (5, 10, 20)
    assert _coerce_amounts([10, 0, 12]) is None
    assert _coerce_amounts([10, -1]) is None
    assert _coerce_amounts("abc") is None
    assert _coerce_amounts(None) is None
    assert _coerce_amounts([]) is None


@pytest.mark.asyncio
async def test_claim_maps_duplicate_payment_marker_to_already_claimed(monkeypatch) -> None:
    from sqlalchemy.exc import IntegrityError

    from app.services import daily_bonus as daily_bonus_module
    from app.services.daily_bonus import AlreadyClaimedError, DailyBonusService

    class _EmptyResult:
        def all(self):
            return []

        def first(self):
            return None

    class _Savepoint:
        def __init__(self) -> None:
            self.committed = False
            self.rolled_back = False

        async def commit(self) -> None:
            self.committed = True

        async def rollback(self) -> None:
            self.rolled_back = True

    class _Session:
        def __init__(self) -> None:
            self.savepoint = _Savepoint()
            self.added = []

        async def execute(self, _stmt):
            return _EmptyResult()

        async def begin_nested(self):
            return self.savepoint

        def add(self, row) -> None:
            self.added.append(row)

    class _TokenService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add(self, **_kwargs):
            raise IntegrityError("insert transaction", {}, Exception("duplicate"))

    monkeypatch.setattr(daily_bonus_module, "TokenService", _TokenService)

    session = _Session()
    service = DailyBonusService(session, redis=None)
    with pytest.raises(AlreadyClaimedError) as excinfo:
        await service.claim(42, now=datetime(2026, 5, 16, 9, 0, tzinfo=UTC))

    assert excinfo.value.next_available_at == datetime(2026, 5, 17, tzinfo=UTC)
    assert session.savepoint.rolled_back is True
    assert session.savepoint.committed is False
    assert session.added == []


# =========================================================================
# DB integration — real Postgres, exercised through ``DailyBonusService``.
# =========================================================================


from app.models import DailyBonusClaim, Transaction, User  # noqa: E402


class _MemoryRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int | None] = {}
        self.set_event = asyncio.Event()

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> None:
        self.values[key] = value
        self.expiries[key] = ex
        self.set_event.set()


@pytest.mark.asyncio
async def test_claim_rollback_does_not_leave_phantom_cache(monkeypatch) -> None:
    from app.services import daily_bonus as daily_bonus_module
    from app.services.daily_bonus import DailyBonusService

    class _EmptyResult:
        def all(self):
            return []

        def first(self):
            return None

    class _Savepoint:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    class _Session:
        def __init__(self) -> None:
            self.added = []
            self.rolled_back = False

        async def execute(self, _stmt):
            return _EmptyResult()

        async def begin_nested(self):
            return _Savepoint()

        def add(self, row) -> None:
            self.added.append(row)

        async def flush(self) -> None:
            return None

        async def rollback(self) -> None:
            self.rolled_back = True

    class _Credit:
        transaction_id = 777
        new_balance = 10

    class _TokenService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add(self, **_kwargs):
            return _Credit()

    monkeypatch.setattr(daily_bonus_module, "TokenService", _TokenService)

    session = _Session()
    redis = _MemoryRedis()
    service = DailyBonusService(session, redis=redis)
    when = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)

    await service.claim(42, now=when)
    await session.rollback()

    assert session.rolled_back is True
    assert redis.values == {}

    snapshot = await service.status(42, now=when)
    assert snapshot.available is True
    assert snapshot.last_claim_date is None


async def _make_user(session, *, telegram_id: int, code: str) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"u{telegram_id}",
        referral_code=code,
        token_balance=0,
    )
    session.add(user)
    await session.flush()
    return user


@pytest.mark.asyncio
async def test_first_claim_credits_and_writes_ledger_row(db_session):
    from app.services.daily_bonus import DailyBonusService

    user = await _make_user(db_session, telegram_id=9_300_001, code="DB-ONE-1")
    svc = DailyBonusService(db_session, redis=None)
    today = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)

    result = await svc.claim(user.id, now=today)

    assert result.amount == 10  # streak day 1 → first value of default ladder
    assert result.streak_day == 1
    assert result.new_balance == 10
    assert result.claim_date == today.date()

    # Ledger row exists and points at the same transaction.
    row = (
        await db_session.execute(
            select(DailyBonusClaim).where(DailyBonusClaim.user_id == user.id)
        )
    ).scalar_one()
    assert row.streak_day == 1
    assert row.amount == 10
    assert row.transaction_id == result.transaction_id

    # Transaction row carries the idempotency marker.
    tx = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == result.transaction_id)
        )
    ).scalar_one()
    assert tx.transaction_type == "bonus"
    assert tx.package_name == "daily_bonus"
    assert tx.payment_id == f"daily_bonus:user:{user.id}:date:2026-05-16"


@pytest.mark.asyncio
async def test_second_claim_same_utc_day_is_blocked(db_session):
    from app.services.daily_bonus import AlreadyClaimedError, DailyBonusService

    user = await _make_user(db_session, telegram_id=9_300_002, code="DB-ONE-2")
    svc = DailyBonusService(db_session, redis=None)
    when = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)
    await svc.claim(user.id, now=when)

    # Re-fetch service to clear any cached state (and prove the DB read alone is enough).
    svc2 = DailyBonusService(db_session, redis=None)
    with pytest.raises(AlreadyClaimedError) as excinfo:
        await svc2.claim(user.id, now=when + timedelta(hours=1))

    next_at = excinfo.value.next_available_at
    assert next_at == datetime.combine(date(2026, 5, 17), dtime(0, 0), tzinfo=UTC)

    # Balance must not have moved.
    await db_session.refresh(user)
    assert user.token_balance == 10


@pytest.mark.asyncio
async def test_streak_grows_across_consecutive_utc_days(db_session):
    from app.services.daily_bonus import DailyBonusService

    user = await _make_user(db_session, telegram_id=9_300_003, code="DB-STK-1")
    svc = DailyBonusService(db_session, redis=None)

    day1 = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    day2 = day1 + timedelta(days=1)
    day3 = day1 + timedelta(days=2)
    day4 = day1 + timedelta(days=3)
    day5 = day1 + timedelta(days=4)

    r1 = await svc.claim(user.id, now=day1)
    r2 = await svc.claim(user.id, now=day2)
    r3 = await svc.claim(user.id, now=day3)
    r4 = await svc.claim(user.id, now=day4)
    r5 = await svc.claim(user.id, now=day5)

    # Ladder: 10, 12, 15, 20; the fifth day reuses the last value.
    assert (r1.amount, r2.amount, r3.amount, r4.amount, r5.amount) == (10, 12, 15, 20, 20)
    assert (r1.streak_day, r2.streak_day, r3.streak_day, r4.streak_day, r5.streak_day) == (
        1, 2, 3, 4, 5,
    )
    assert r5.new_balance == 10 + 12 + 15 + 20 + 20

    rows = (
        await db_session.execute(
            select(DailyBonusClaim)
            .where(DailyBonusClaim.user_id == user.id)
            .order_by(DailyBonusClaim.claim_date.asc())
        )
    ).scalars().all()
    assert [r.streak_day for r in rows] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_skipped_day_resets_streak(db_session):
    from app.services.daily_bonus import DailyBonusService

    user = await _make_user(db_session, telegram_id=9_300_004, code="DB-STK-2")
    svc = DailyBonusService(db_session, redis=None)

    day1 = datetime(2026, 5, 10, 12, 0, tzinfo=UTC)
    day2 = day1 + timedelta(days=1)
    # Skip day 3 — claim on day 4.
    day4 = day1 + timedelta(days=3)

    r1 = await svc.claim(user.id, now=day1)
    r2 = await svc.claim(user.id, now=day2)
    r4 = await svc.claim(user.id, now=day4)

    assert (r1.streak_day, r2.streak_day, r4.streak_day) == (1, 2, 1)
    # First-tier reward returns after the reset.
    assert r4.amount == 10


@pytest.mark.asyncio
async def test_status_reflects_already_claimed_and_streak(db_session):
    from app.services.daily_bonus import DailyBonusService

    user = await _make_user(db_session, telegram_id=9_300_005, code="DB-STT-1")
    svc = DailyBonusService(db_session, redis=None)
    today = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)

    await svc.claim(user.id, now=today)
    snapshot = await svc.status(user.id, now=today + timedelta(hours=2))

    assert snapshot.available is False
    assert snapshot.enabled is True
    assert snapshot.streak_day == 1
    # Preview: tomorrow would land on streak day 2 → 12 tokens.
    assert snapshot.next_amount == 12
    assert snapshot.last_claim_date == today.date()
    assert snapshot.next_available_at == datetime.combine(
        date(2026, 5, 17), dtime(0, 0), tzinfo=UTC
    )


@pytest.mark.asyncio
async def test_status_fresh_user_is_available(db_session):
    from app.services.daily_bonus import DailyBonusService

    user = await _make_user(db_session, telegram_id=9_300_006, code="DB-STT-2")
    svc = DailyBonusService(db_session, redis=None)

    snapshot = await svc.status(user.id, now=datetime(2026, 5, 16, tzinfo=UTC))
    assert snapshot.available is True
    assert snapshot.enabled is True
    assert snapshot.next_amount == 10  # would be streak day 1
    assert snapshot.last_claim_date is None


@pytest.mark.asyncio
async def test_rollback_after_claim_does_not_cache_phantom_claim(db_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.services.daily_bonus import DailyBonusService

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    redis = _MemoryRedis()
    when = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)

    async with factory() as setup:
        user = User(
            telegram_id=9_300_013,
            username="daily-rollback",
            referral_code="DB-RB-1",
            token_balance=0,
        )
        setup.add(user)
        await setup.commit()
        user_id = int(user.id)

    try:
        async with factory() as failed_session:
            service = DailyBonusService(failed_session, redis=redis)
            await service.claim(user_id, now=when)
            await failed_session.rollback()

        async with factory() as retry_session:
            service = DailyBonusService(retry_session, redis=redis)
            status = await service.status(user_id, now=when)
            assert status.available is True

            retry = await service.claim(user_id, now=when)
            assert retry.amount == 10
            await retry_session.commit()

        await asyncio.wait_for(redis.set_event.wait(), timeout=1)
        assert json.loads(redis.values[f"daily_bonus:user:{user_id}"]) == {
            "claim_date": "2026-05-16",
            "streak_day": 1,
        }

        async with factory() as verify:
            claim_count = (
                await verify.execute(
                    select(func.count())
                    .select_from(DailyBonusClaim)
                    .where(DailyBonusClaim.user_id == user_id)
                )
            ).scalar_one()
            balance = (
                await verify.execute(select(User.token_balance).where(User.id == user_id))
            ).scalar_one()

        assert claim_count == 1
        assert balance == 10
    finally:
        async with factory() as cleanup:
            await cleanup.execute(
                DailyBonusClaim.__table__.delete().where(
                    DailyBonusClaim.user_id == user_id
                )
            )
            await cleanup.execute(
                Transaction.__table__.delete().where(Transaction.user_id == user_id)
            )
            user = (
                await cleanup.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is not None:
                await cleanup.delete(user)
            await cleanup.commit()


@pytest.mark.asyncio
async def test_unique_constraint_blocks_double_claim_under_race(db_session):
    """Two concurrent claims for the same UTC day must not both succeed.

    The service-level guard is bypassed by hand-crafting a second insert,
    which the DB UNIQUE constraint must still reject.
    """
    from sqlalchemy.exc import IntegrityError

    from app.services.daily_bonus import DailyBonusService

    user = await _make_user(db_session, telegram_id=9_300_007, code="DB-RACE-1")
    svc = DailyBonusService(db_session, redis=None)
    when = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)

    await svc.claim(user.id, now=when)

    duplicate = DailyBonusClaim(
        user_id=user.id,
        claim_date=when.date(),
        streak_day=1,
        amount=10,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_admin_setting_override_changes_ladder(db_session):
    from app.models.admin_setting import AdminSetting
    from app.services.daily_bonus import (
        ADMIN_SETTING_AMOUNTS,
        DailyBonusService,
    )

    db_session.add(
        AdminSetting(
            setting_key=ADMIN_SETTING_AMOUNTS,
            setting_value={"amounts": [1, 2, 3]},
        )
    )
    await db_session.flush()

    user = await _make_user(db_session, telegram_id=9_300_008, code="DB-CFG-1")
    svc = DailyBonusService(db_session, redis=None)

    result = await svc.claim(user.id, now=datetime(2026, 5, 16, tzinfo=UTC))
    assert result.amount == 1
    snapshot = await svc.status(user.id, now=datetime(2026, 5, 16, tzinfo=UTC))
    assert list(snapshot.amounts) == [1, 2, 3]
    assert snapshot.next_amount == 2  # would-be streak day 2


@pytest.mark.asyncio
async def test_admin_setting_can_disable_loop(db_session):
    from app.models.admin_setting import AdminSetting
    from app.services.daily_bonus import (
        ADMIN_SETTING_ENABLED,
        DailyBonusDisabledError,
        DailyBonusService,
    )

    db_session.add(
        AdminSetting(
            setting_key=ADMIN_SETTING_ENABLED,
            setting_value={"enabled": False},
        )
    )
    await db_session.flush()

    user = await _make_user(db_session, telegram_id=9_300_009, code="DB-CFG-2")
    svc = DailyBonusService(db_session, redis=None)

    with pytest.raises(DailyBonusDisabledError):
        await svc.claim(user.id, now=datetime(2026, 5, 16, tzinfo=UTC))

    snapshot = await svc.status(user.id, now=datetime(2026, 5, 16, tzinfo=UTC))
    assert snapshot.enabled is False
    assert snapshot.available is False


# =========================================================================
# Endpoint tests — in-memory stubs, no DB.
# =========================================================================


class _Settings:
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
        self.is_premium = False
        self.premium_expires_at = None
        self.token_balance = 0
        self.total_tokens_purchased = 0
        self.total_tokens_spent = 0
        self.total_requests = 0
        self.last_active_at = datetime.now(UTC)
        self.last_login_at = None


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


class _StubService:
    """Captures calls and returns scripted status/claim results."""

    def __init__(
        self,
        *,
        status_payload,
        claim_result=None,
        claim_error: Exception | None = None,
    ) -> None:
        self._status = status_payload
        self._claim_result = claim_result
        self._claim_error = claim_error
        self.status_calls: list[int] = []
        self.claim_calls: list[int] = []

    async def status(self, user_id, *, now=None):
        self.status_calls.append(user_id)
        return self._status

    async def claim(self, user_id, *, now=None):
        self.claim_calls.append(user_id)
        if self._claim_error is not None:
            raise self._claim_error
        return self._claim_result


@pytest.fixture
def daily_bonus_app(monkeypatch):
    from app.api.v1 import user as user_module
    from app.auth import dependencies as deps
    from app.main import create_app
    from app.services import users as users_module

    settings = _Settings()
    user = _ApiUser(id=42, telegram_id=42)
    store: dict[int, _ApiUser] = {user.telegram_id: user}
    holder: dict[str, _StubService | None] = {"service": None}

    async def fake_upsert(_session, *, telegram_user, super_admin_ids):
        tid = int(telegram_user["id"])
        existing = store.get(tid)
        if existing is None:
            new_user = _ApiUser(id=tid, telegram_id=tid)
            store[tid] = new_user
            return new_user, True
        return existing, False

    async def fake_find_by_id(_session, user_id):
        for u in store.values():
            if u.id == user_id:
                return u
        return None

    class _NoOpSession:
        async def commit(self) -> None:
            return None

        async def rollback(self) -> None:
            return None

    async def fake_get_session():
        yield _NoOpSession()

    monkeypatch.setattr(users_module, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(users_module, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "upsert_telegram_user", fake_upsert)
    monkeypatch.setattr(deps, "find_user_by_id", fake_find_by_id)
    monkeypatch.setattr(deps, "get_session", fake_get_session)
    monkeypatch.setattr(deps, "get_settings", lambda: settings)
    monkeypatch.setattr("app.core.config.get_settings", lambda: settings, raising=True)
    monkeypatch.setattr(user_module, "get_settings", lambda: settings)

    def fake_service(*_args, **_kwargs):
        assert holder["service"] is not None, "test must assign a stub service first"
        return holder["service"]

    monkeypatch.setattr(user_module, "DailyBonusService", fake_service)
    monkeypatch.setattr(user_module, "TokenService", _TokenServiceStub)

    app = create_app()
    from app.auth.dependencies import _settings_dep
    from app.core.database import get_session as real_get_session

    async def _yield_noop_session():
        yield _NoOpSession()

    app.dependency_overrides[real_get_session] = _yield_noop_session
    app.dependency_overrides[_settings_dep] = lambda: settings
    app.dependency_overrides[user_module._redis_dep] = lambda: None

    return app, store, holder


class _TokenServiceStub:
    def __init__(self, _session) -> None:
        pass

    async def get_balance(self, _user_id: int) -> int:
        return 0


@pytest.mark.asyncio
async def test_get_daily_bonus_status_returns_snapshot(daily_bonus_app) -> None:
    from app.services.daily_bonus import DailyBonusStatus

    app, _store, holder = daily_bonus_app
    holder["service"] = _StubService(
        status_payload=DailyBonusStatus(
            available=True,
            enabled=True,
            streak_day=0,
            next_amount=10,
            last_claim_date=None,
            next_available_at=datetime(2026, 5, 17, tzinfo=UTC),
            amounts=(10, 12, 15, 20),
        )
    )
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.get(
            "/api/v1/user/daily-bonus",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is True
    assert body["enabled"] is True
    assert body["streak_day"] == 0
    assert body["next_amount"] == 10
    assert body["amounts"] == [10, 12, 15, 20]
    assert body["last_claim_date"] is None
    assert body["next_available_at"].startswith("2026-05-17")


@pytest.mark.asyncio
async def test_post_daily_bonus_credits_tokens(daily_bonus_app) -> None:
    from app.services.daily_bonus import DailyBonusClaimResult, DailyBonusStatus

    app, _store, holder = daily_bonus_app
    holder["service"] = _StubService(
        status_payload=DailyBonusStatus(
            available=True,
            enabled=True,
            streak_day=0,
            next_amount=10,
            last_claim_date=None,
            next_available_at=datetime(2026, 5, 17, tzinfo=UTC),
            amounts=(10, 12, 15, 20),
        ),
        claim_result=DailyBonusClaimResult(
            amount=10,
            streak_day=1,
            new_balance=110,
            transaction_id=777,
            claim_date=date(2026, 5, 16),
            next_available_at=datetime(2026, 5, 17, tzinfo=UTC),
        ),
    )
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/daily-bonus",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["amount"] == 10
    assert body["streak_day"] == 1
    assert body["new_balance"] == 110
    assert body["transaction_id"] == 777
    assert body["claim_date"] == "2026-05-16"
    assert holder["service"].claim_calls == [42]


@pytest.mark.asyncio
async def test_post_daily_bonus_returns_409_when_already_claimed(daily_bonus_app) -> None:
    from app.services.daily_bonus import (
        AlreadyClaimedError,
        DailyBonusStatus,
    )

    next_at = datetime(2026, 5, 17, tzinfo=UTC)
    app, _store, holder = daily_bonus_app
    holder["service"] = _StubService(
        status_payload=DailyBonusStatus(
            available=False,
            enabled=True,
            streak_day=1,
            next_amount=12,
            last_claim_date=date(2026, 5, 16),
            next_available_at=next_at,
            amounts=(10, 12, 15, 20),
        ),
        claim_error=AlreadyClaimedError(next_available_at=next_at),
    )
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/daily-bonus",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["code"] == "daily_bonus_already_claimed"
    assert detail["next_available_at"].startswith("2026-05-17")


@pytest.mark.asyncio
async def test_post_daily_bonus_returns_403_when_disabled(daily_bonus_app) -> None:
    from app.services.daily_bonus import (
        DailyBonusDisabledError,
        DailyBonusStatus,
    )

    app, _store, holder = daily_bonus_app
    holder["service"] = _StubService(
        status_payload=DailyBonusStatus(
            available=False,
            enabled=False,
            streak_day=0,
            next_amount=10,
            last_claim_date=None,
            next_available_at=datetime(2026, 5, 17, tzinfo=UTC),
            amounts=(10, 12, 15, 20),
        ),
        claim_error=DailyBonusDisabledError("disabled"),
    )
    init = _build_init_data(telegram_id=42)
    async with await _client(app) as c:
        resp = await c.post(
            "/api/v1/user/daily-bonus",
            headers={"X-Telegram-Init-Data": init},
        )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "daily_bonus_disabled"


@pytest.mark.asyncio
async def test_daily_bonus_endpoints_require_init_data(daily_bonus_app) -> None:
    app, _store, _holder = daily_bonus_app
    async with await _client(app) as c:
        get_resp = await c.get("/api/v1/user/daily-bonus")
        post_resp = await c.post("/api/v1/user/daily-bonus")
    assert get_resp.status_code == 401
    assert post_resp.status_code == 401
    assert get_resp.json()["detail"] == "missing_init_data"


# ----- "different timezone" — verifies UTC-only day boundary semantics -----


@pytest.mark.asyncio
async def test_utc_midnight_is_the_day_boundary(db_session):
    """A claim 23:59 UTC and 00:01 UTC are on different days even though
    they are seconds apart in wall-clock for non-UTC observers."""
    from app.services.daily_bonus import DailyBonusService

    user = await _make_user(db_session, telegram_id=9_300_010, code="DB-TZ-1")
    svc = DailyBonusService(db_session, redis=None)

    # 23:59:30 UTC on day N.
    late = datetime(2026, 5, 16, 23, 59, 30, tzinfo=UTC)
    # 00:00:30 UTC on day N+1 (one minute later in wall-clock).
    early = datetime(2026, 5, 17, 0, 0, 30, tzinfo=UTC)

    r_late = await svc.claim(user.id, now=late)
    r_early = await svc.claim(user.id, now=early)

    assert r_late.streak_day == 1
    assert r_early.streak_day == 2  # consecutive UTC days
    assert r_late.amount == 10
    assert r_early.amount == 12


@pytest.mark.asyncio
async def test_concurrent_spam_is_idempotent(db_session):
    """Hammering the endpoint within the same UTC day must result in
    exactly one credit (verified through the service surface)."""
    from app.services.daily_bonus import AlreadyClaimedError, DailyBonusService

    user = await _make_user(db_session, telegram_id=9_300_011, code="DB-SPAM-1")
    svc = DailyBonusService(db_session, redis=None)
    when = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)

    successes = 0
    rejections = 0
    for _ in range(5):
        try:
            await svc.claim(user.id, now=when)
            successes += 1
        except AlreadyClaimedError:
            rejections += 1

    assert successes == 1
    assert rejections == 4

    # Ledger has exactly one row.
    rows = (
        await db_session.execute(
            select(DailyBonusClaim).where(DailyBonusClaim.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_concurrent_claim_duplicate_transaction_marker_is_clean(db_engine, monkeypatch):
    """A losing concurrent claim must return AlreadyClaimed and leave its session usable."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.services.daily_bonus import (
        AlreadyClaimedError,
        DailyBonusService,
        _payment_id,
    )

    factory = async_sessionmaker(db_engine, expire_on_commit=False, class_=AsyncSession)
    when = datetime(2026, 5, 16, 9, 0, tzinfo=UTC)

    async with factory() as setup:
        user = User(
            telegram_id=9_300_012,
            username="daily-race",
            referral_code="DB-RACE-2",
            token_balance=0,
        )
        setup.add(user)
        await setup.commit()
        user_id = int(user.id)

    original_read_latest = DailyBonusService._read_latest_from_db
    read_count = 0
    read_lock = asyncio.Lock()
    both_checked_latest = asyncio.Event()

    async def wait_until_both_claims_checked_latest(self, requested_user_id):
        nonlocal read_count
        latest = await original_read_latest(self, requested_user_id)
        if requested_user_id == user_id:
            async with read_lock:
                read_count += 1
                if read_count == 2:
                    both_checked_latest.set()
            await asyncio.wait_for(both_checked_latest.wait(), timeout=5)
        return latest

    monkeypatch.setattr(
        DailyBonusService,
        "_read_latest_from_db",
        wait_until_both_claims_checked_latest,
    )

    try:
        async def attempt() -> str:
            async with factory() as session:
                service = DailyBonusService(session, redis=None)
                try:
                    await service.claim(user_id, now=when)
                except AlreadyClaimedError:
                    # The session must not be left in PostgreSQL's aborted
                    # transaction state after the duplicate payment marker.
                    usable = (
                        await session.execute(select(User.id).where(User.id == user_id))
                    ).scalar_one()
                    assert usable == user_id
                    await session.rollback()
                    return "already"

                await session.commit()
                return "claimed"

        results = await asyncio.gather(attempt(), attempt())
        assert sorted(results) == ["already", "claimed"]

        async with factory() as verify:
            claim_count = (
                await verify.execute(
                    select(func.count())
                    .select_from(DailyBonusClaim)
                    .where(DailyBonusClaim.user_id == user_id)
                )
            ).scalar_one()
            tx_count = (
                await verify.execute(
                    select(func.count())
                    .select_from(Transaction)
                    .where(Transaction.payment_id == _payment_id(user_id, when.date()))
                )
            ).scalar_one()
            balance = (
                await verify.execute(select(User.token_balance).where(User.id == user_id))
            ).scalar_one()

        assert claim_count == 1
        assert tx_count == 1
        assert balance == 10
    finally:
        async with factory() as cleanup:
            await cleanup.execute(
                DailyBonusClaim.__table__.delete().where(
                    DailyBonusClaim.user_id == user_id
                )
            )
            await cleanup.execute(
                Transaction.__table__.delete().where(Transaction.user_id == user_id)
            )
            user = (
                await cleanup.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is not None:
                await cleanup.delete(user)
            await cleanup.commit()
