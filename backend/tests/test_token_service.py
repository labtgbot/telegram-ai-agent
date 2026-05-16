"""Unit tests for :mod:`app.services.token_service`.

The pure-unit tests in this module exercise input validation and the
``InsufficientTokensError`` payload — no database required.  The
database-backed scenarios live in ``test_token_service_db.py``.
"""
from __future__ import annotations

import pytest

from app.services.balance_cache import BalanceCache
from app.services.token_service import (
    CREDIT_TYPES,
    REFUNDABLE_TYPES,
    BalanceAudit,
    InsufficientTokensError,
    InvalidAmountError,
    SpendResult,
    TokenOperationResult,
    TokenService,
    UsageHistoryPage,
    UserNotFoundError,
    _coerce_amount,
)

# ---------------------------------------------------------------- _coerce_amount


@pytest.mark.parametrize("value", [1, 5, 1_000])
def test_coerce_amount_accepts_positive_int(value: int) -> None:
    assert _coerce_amount(value) == value


@pytest.mark.parametrize("value", [0, -1, -1_000])
def test_coerce_amount_rejects_non_positive(value: int) -> None:
    with pytest.raises(InvalidAmountError):
        _coerce_amount(value)


@pytest.mark.parametrize("value", [True, False])
def test_coerce_amount_rejects_bool(value: bool) -> None:
    """``bool`` is a subclass of ``int`` in Python — must be rejected explicitly."""
    with pytest.raises(InvalidAmountError):
        _coerce_amount(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["10", 1.5, None, [1], object()])
def test_coerce_amount_rejects_non_int(value: object) -> None:
    with pytest.raises(InvalidAmountError):
        _coerce_amount(value)  # type: ignore[arg-type]


# ---------------------------------------------------------------- exceptions


def test_insufficient_tokens_error_exposes_required_and_available() -> None:
    err = InsufficientTokensError(required=100, available=20)
    assert err.required == 100
    assert err.available == 20
    msg = str(err)
    assert "100" in msg
    assert "20" in msg


# ---------------------------------------------------------------- result types


def test_token_operation_result_is_immutable_dataclass() -> None:
    result = TokenOperationResult(
        user_id=1, amount=10, new_balance=50, transaction_id=99, transaction_type="bonus"
    )
    with pytest.raises((AttributeError, Exception)):
        result.amount = 11  # type: ignore[misc]


def test_spend_result_carries_usage_log_id() -> None:
    result = SpendResult(
        user_id=1,
        amount=10,
        new_balance=40,
        transaction_id=99,
        transaction_type="spend",
        usage_log_id=42,
    )
    assert result.usage_log_id == 42
    assert result.transaction_type == "spend"


def test_usage_history_page_has_more_flag() -> None:
    page = UsageHistoryPage(items=[], total=50, page=1, limit=20)
    assert page.has_more is True
    last = UsageHistoryPage(items=[], total=40, page=2, limit=20)
    assert last.has_more is False
    empty = UsageHistoryPage(items=[], total=0, page=1, limit=20)
    assert empty.has_more is False


def test_balance_audit_is_consistent() -> None:
    clean = BalanceAudit(user_id=1, stored_balance=100, computed_balance=100, drift=0)
    drifted = BalanceAudit(user_id=2, stored_balance=100, computed_balance=90, drift=10)
    assert clean.is_consistent is True
    assert drifted.is_consistent is False


# ---------------------------------------------------------------- constants


def test_credit_types_are_well_known() -> None:
    assert "bonus" in CREDIT_TYPES
    assert "purchase" in CREDIT_TYPES
    assert "manual_bonus" in CREDIT_TYPES
    assert "spend" not in CREDIT_TYPES
    assert "refund" not in CREDIT_TYPES


def test_refundable_types_cover_purchase_and_spend_only() -> None:
    assert frozenset({"spend", "purchase"}) == REFUNDABLE_TYPES


# ---------------------------------------------------------- argument validation


@pytest.mark.asyncio
async def test_add_rejects_invalid_amount_before_touching_session() -> None:
    """``add`` validates the amount *before* the session is touched."""

    class ExplodingSession:
        async def execute(self, *_a, **_kw):
            raise AssertionError("session must not be hit on validation failure")

        def add(self, *_a, **_kw):
            raise AssertionError("session must not be hit on validation failure")

        async def flush(self):
            raise AssertionError("session must not be hit on validation failure")

    svc = TokenService(ExplodingSession())  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        await svc.add(user_id=1, amount=0)


@pytest.mark.asyncio
async def test_add_rejects_unknown_transaction_type() -> None:
    class ExplodingSession:
        async def execute(self, *_a, **_kw):
            raise AssertionError("session must not be hit on validation failure")

    svc = TokenService(ExplodingSession())  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        await svc.add(user_id=1, amount=10, transaction_type="spend")
    with pytest.raises(InvalidAmountError):
        await svc.add(user_id=1, amount=10, transaction_type="refund")


@pytest.mark.asyncio
async def test_spend_rejects_blank_service() -> None:
    class ExplodingSession:
        async def execute(self, *_a, **_kw):
            raise AssertionError("session must not be hit on validation failure")

    svc = TokenService(ExplodingSession())  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        await svc.spend(user_id=1, amount=10, service="")
    with pytest.raises(InvalidAmountError):
        await svc.spend(user_id=1, amount=10, service="   ")


@pytest.mark.asyncio
async def test_manual_bonus_requires_reason() -> None:
    class ExplodingSession:
        async def execute(self, *_a, **_kw):
            raise AssertionError("session must not be hit on validation failure")

    svc = TokenService(ExplodingSession())  # type: ignore[arg-type]
    with pytest.raises(InvalidAmountError):
        await svc.manual_bonus(user_id=1, amount=10, reason="")
    with pytest.raises(InvalidAmountError):
        await svc.manual_bonus(user_id=1, amount=10, reason="   ")


# ---------------------------------------------------- get_balance + cache wiring


class _StubRedis:
    """Async ``redis.asyncio``-shaped stub used only for cache tests."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.get_calls: list[str] = []

    async def get(self, name: str):
        self.get_calls.append(name)
        return self.store.get(name)

    async def set(self, name: str, value, ex=None) -> bool:  # noqa: ANN001
        self.store[name] = str(value)
        return True

    async def delete(self, *names: str) -> int:
        removed = 0
        for n in names:
            if n in self.store:
                del self.store[n]
                removed += 1
        return removed


class _SessionRecorder:
    """Pretends to be an :class:`AsyncSession` for ``get_balance`` reads.

    Returns a one-row scalar wrapped in a tiny shim so we can assert how
    many times ``session.execute`` is actually called.
    """

    def __init__(self, balance: int | None) -> None:
        self.balance = balance
        self.execute_calls = 0

    async def execute(self, _stmt):  # noqa: ANN001
        self.execute_calls += 1
        balance = self.balance

        class _Result:
            def scalar_one_or_none(self_inner) -> int | None:
                return balance

        return _Result()


@pytest.mark.asyncio
async def test_get_balance_returns_cached_value_without_db_hit() -> None:
    redis = _StubRedis()
    cache = BalanceCache(redis, ttl_seconds=60)
    await cache.set(42, 250)

    session = _SessionRecorder(balance=999)  # would-be DB value, must not be read
    svc = TokenService(session, cache)  # type: ignore[arg-type]

    assert await svc.get_balance(42) == 250
    assert session.execute_calls == 0


@pytest.mark.asyncio
async def test_get_balance_populates_cache_on_miss() -> None:
    redis = _StubRedis()
    cache = BalanceCache(redis, ttl_seconds=60)

    session = _SessionRecorder(balance=125)
    svc = TokenService(session, cache)  # type: ignore[arg-type]

    assert await svc.get_balance(7) == 125
    assert session.execute_calls == 1
    # Hydrated — a subsequent read serves from cache.
    assert await svc.get_balance(7) == 125
    assert session.execute_calls == 1
    assert await cache.get(7) == 125


@pytest.mark.asyncio
async def test_get_balance_falls_back_to_session_when_no_cache() -> None:
    session = _SessionRecorder(balance=42)
    svc = TokenService(session)  # type: ignore[arg-type]
    assert await svc.get_balance(99) == 42
    assert session.execute_calls == 1


@pytest.mark.asyncio
async def test_get_balance_raises_when_user_missing_and_no_cache() -> None:
    session = _SessionRecorder(balance=None)
    svc = TokenService(session)  # type: ignore[arg-type]
    with pytest.raises(UserNotFoundError):
        await svc.get_balance(404)


@pytest.mark.asyncio
async def test_refresh_cache_swallows_redis_outage() -> None:
    """A Redis failure must never break a billable spend."""

    class _BrokenRedis(_StubRedis):
        async def set(self, *_a, **_kw) -> bool:
            raise RuntimeError("redis down")

    cache = BalanceCache(_BrokenRedis(), ttl_seconds=60)
    svc = TokenService(_SessionRecorder(balance=0), cache)  # type: ignore[arg-type]
    # _refresh_cache is the codepath every write method calls post-flush;
    # it must absorb backend errors silently.
    await svc._refresh_cache(1, 500)
