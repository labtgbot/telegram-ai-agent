"""Database-backed integration tests for :class:`TokenService`.

These exercise the *actual* atomic semantics:

* ``add`` increments balance and writes a ``Transaction`` row.
* ``spend`` debits balance, writes a ``Transaction``, and writes the
  corresponding ``TokenUsageLog`` row (which lands in a partition).
* ``InsufficientTokensError`` is raised before any mutation, leaving the
  user balance untouched.
* ``manual_bonus`` and ``refund`` adjust user totals correctly.
* ``reconcile_user_balance`` detects drift between the materialised
  balance and the transaction ledger.

The fixture in ``conftest.py`` skips these automatically when no
``DATABASE_URL`` is configured.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import Transaction, User
from app.models.token_usage_log import TokenUsageLog
from app.services.balance_cache import BalanceCache
from app.services.token_service import (
    InsufficientTokensError,
    InvalidAmountError,
    TokenService,
    TransactionNotFoundError,
    TransactionNotRefundableError,
    UserNotFoundError,
    reconcile_all_balances,
    reconcile_user_balance,
)


class _StubRedis:
    """Async Redis-shaped stub used for balance cache assertions."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, name: str):
        return self.store.get(name)

    async def set(self, name: str, value, ex=None) -> bool:  # noqa: ANN001
        self.store[name] = str(value)
        return True

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if name in self.store:
                del self.store[name]
                removed += 1
        return removed


async def _make_user(session, *, telegram_id: int, code: str, balance: int = 0) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"u{telegram_id}",
        referral_code=code,
        token_balance=balance,
    )
    session.add(user)
    await session.flush()
    return user


# --------------------------------------------------------------------- add


@pytest.mark.asyncio
async def test_add_credits_balance_and_records_transaction(db_session):
    user = await _make_user(db_session, telegram_id=8_000_001, code="TS-ADD-1")
    svc = TokenService(db_session)

    result = await svc.add(user_id=user.id, amount=100, transaction_type="bonus")
    assert result.amount == 100
    assert result.new_balance == 100
    assert result.transaction_type == "bonus"
    assert result.transaction_id > 0

    await db_session.refresh(user)
    assert user.token_balance == 100

    tx = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == result.transaction_id)
        )
    ).scalar_one()
    assert tx.tokens_amount == 100
    assert tx.transaction_type == "bonus"
    assert tx.payment_status == "completed"
    assert tx.completed_at is not None


@pytest.mark.asyncio
async def test_add_purchase_updates_total_tokens_purchased(db_session):
    user = await _make_user(db_session, telegram_id=8_000_002, code="TS-ADD-2")
    svc = TokenService(db_session)

    await svc.add(
        user_id=user.id,
        amount=500,
        transaction_type="purchase",
        package_name="basic",
        stars_amount=250,
        usd_amount=Decimal("5.00"),
    )
    await db_session.refresh(user)
    assert user.token_balance == 500
    assert user.total_tokens_purchased == 500


@pytest.mark.asyncio
async def test_add_rejects_unknown_user(db_session):
    svc = TokenService(db_session)
    with pytest.raises(UserNotFoundError):
        await svc.add(user_id=999_999_999, amount=10)


# --------------------------------------------------------------------- spend


@pytest.mark.asyncio
async def test_spend_debits_balance_and_writes_usage_log(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_003, code="TS-SPEND-1", balance=200
    )
    svc = TokenService(db_session)
    long_tool = "image_tool_" + ("x" * 300)
    long_server = "mcp_server_" + ("y" * 300)

    result = await svc.spend(
        user_id=user.id,
        amount=50,
        service="image_generation",
        request_params={"prompt": "cat"},
        processing_time_ms=120,
        composio_tool=long_tool,
        mcp_server=long_server,
    )
    assert result.new_balance == 150
    assert result.amount == 50
    assert result.transaction_type == "spend"
    assert result.usage_log_id > 0

    await db_session.refresh(user)
    assert user.token_balance == 150
    assert user.total_tokens_spent == 50
    assert user.total_requests == 1

    log = (
        await db_session.execute(
            select(TokenUsageLog).where(TokenUsageLog.id == result.usage_log_id)
        )
    ).scalar_one()
    assert log.tokens_consumed == 50
    assert log.service_type == "image_generation"
    assert log.request_params == {"prompt": "cat"}
    assert log.composio_tool == long_tool[:255]
    assert log.mcp_server == long_server[:255]


@pytest.mark.asyncio
async def test_record_spend_result_updates_usage_log_metadata(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_020, code="TS-SPEND-META", balance=200
    )
    svc = TokenService(db_session)

    result = await svc.spend(
        user_id=user.id,
        amount=30,
        service="image",
        request_params={"prompt": "cat"},
        response_status="pending",
    )

    await svc.record_spend_result(
        usage_log_id=result.usage_log_id,
        response_status="ok",
        processing_time_ms=321,
        composio_tool="image_gen",
        mcp_server="composio-prod-1",
        request_params={"prompt": "cat", "quality": "standard"},
    )

    log = (
        await db_session.execute(
            select(TokenUsageLog).where(TokenUsageLog.id == result.usage_log_id)
        )
    ).scalar_one()
    assert log.response_status == "ok"
    assert log.processing_time_ms == 321
    assert log.composio_tool == "image_gen"
    assert log.mcp_server == "composio-prod-1"
    assert log.request_params == {"prompt": "cat", "quality": "standard"}


@pytest.mark.asyncio
async def test_spend_raises_insufficient_tokens_without_mutating_state(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_004, code="TS-SPEND-2", balance=10
    )
    svc = TokenService(db_session)

    with pytest.raises(InsufficientTokensError) as exc:
        await svc.spend(user_id=user.id, amount=100, service="image_generation")
    assert exc.value.required == 100
    assert exc.value.available == 10

    await db_session.refresh(user)
    assert user.token_balance == 10
    assert user.total_tokens_spent == 0
    assert user.total_requests == 0

    # No spend transaction was written.
    rows = (
        await db_session.execute(
            select(Transaction).where(
                Transaction.user_id == user.id,
                Transaction.transaction_type == "spend",
            )
        )
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_spend_at_exact_balance_succeeds(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_005, code="TS-SPEND-3", balance=30
    )
    svc = TokenService(db_session)
    result = await svc.spend(user_id=user.id, amount=30, service="text_query")
    assert result.new_balance == 0


@pytest.mark.asyncio
async def test_spend_rollback_does_not_cache_uncommitted_balance(db_engine):
    """A rolled-back spend must not leave its flushed balance in Redis."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(
        db_engine, expire_on_commit=False, class_=AsyncSession
    )
    cache = BalanceCache(_StubRedis(), ttl_seconds=60)
    user_id: int | None = None

    async with factory() as setup:
        user = User(
            telegram_id=8_000_019,
            username="rollback-cache",
            referral_code="TS-SPEND-RB",
            token_balance=200,
        )
        setup.add(user)
        await setup.commit()
        user_id = int(user.id)

    try:
        await cache.set(user_id, 200)
        async with factory() as spend_session:
            svc = TokenService(spend_session, cache)
            spent = await svc.spend(
                user_id=user_id, amount=50, service="text_query"
            )
            assert spent.new_balance == 150
            assert await cache.get(user_id) is None
            await spend_session.rollback()

        async with factory() as verify:
            stored_balance = (
                await verify.execute(
                    select(User.token_balance).where(User.id == user_id)
                )
            ).scalar_one()
            assert stored_balance == 200
            assert await TokenService(verify, cache).get_balance(user_id) == 200
            assert await cache.get(user_id) == 200
    finally:
        if user_id is not None:
            async with factory() as cleanup:
                await cleanup.execute(
                    TokenUsageLog.__table__.delete().where(
                        TokenUsageLog.user_id == user_id
                    )
                )
                await cleanup.execute(
                    Transaction.__table__.delete().where(
                        Transaction.user_id == user_id
                    )
                )
                user = (
                    await cleanup.execute(select(User).where(User.id == user_id))
                ).scalar_one_or_none()
                if user is not None:
                    await cleanup.delete(user)
                await cleanup.commit()


# --------------------------------------------------------- balance / history


@pytest.mark.asyncio
async def test_get_balance_returns_current_value(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_006, code="TS-BAL-1", balance=77
    )
    svc = TokenService(db_session)
    assert await svc.get_balance(user.id) == 77


@pytest.mark.asyncio
async def test_get_balance_unknown_user_raises(db_session):
    svc = TokenService(db_session)
    with pytest.raises(UserNotFoundError):
        await svc.get_balance(123_456_789)


@pytest.mark.asyncio
async def test_usage_history_paginates(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_007, code="TS-HIST-1", balance=1_000
    )
    svc = TokenService(db_session)
    for i in range(5):
        await svc.spend(user_id=user.id, amount=10, service=f"svc_{i}")

    first = await svc.usage_history(user.id, page=1, limit=2)
    assert first.total == 5
    assert first.limit == 2
    assert first.page == 1
    assert first.has_more is True
    assert len(first.items) == 2

    third = await svc.usage_history(user.id, page=3, limit=2)
    assert third.has_more is False
    assert len(third.items) == 1


@pytest.mark.asyncio
async def test_usage_history_clamps_limit_and_page(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_008, code="TS-HIST-2", balance=10
    )
    svc = TokenService(db_session)
    page = await svc.usage_history(user.id, page=0, limit=0)
    assert page.page == 1
    assert page.limit >= 1
    big = await svc.usage_history(user.id, page=1, limit=10_000)
    assert big.limit <= 100


@pytest.mark.asyncio
async def test_usage_history_unknown_user_raises(db_session):
    svc = TokenService(db_session)
    with pytest.raises(UserNotFoundError):
        await svc.usage_history(123_456_789)


# ---------------------------------------------------------------- manual bonus


@pytest.mark.asyncio
async def test_manual_bonus_uses_admin_metadata(db_session):
    user = await _make_user(db_session, telegram_id=8_000_009, code="TS-MB-1")
    svc = TokenService(db_session)

    result = await svc.manual_bonus(
        user_id=user.id,
        amount=42,
        reason="goodwill",
        admin_id=7,
    )
    assert result.transaction_type == "manual_bonus"

    tx = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == result.transaction_id)
        )
    ).scalar_one()
    assert tx.transaction_type == "manual_bonus"
    assert tx.package_name == "goodwill"


@pytest.mark.asyncio
async def test_manual_bonus_invalid_amount_rejected(db_session):
    user = await _make_user(db_session, telegram_id=8_000_010, code="TS-MB-2")
    svc = TokenService(db_session)
    with pytest.raises(InvalidAmountError):
        await svc.manual_bonus(user_id=user.id, amount=-5, reason="bad")


# --------------------------------------------------------------------- refund


@pytest.mark.asyncio
async def test_refund_of_spend_credits_user_back(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_011, code="TS-REF-1", balance=100
    )
    svc = TokenService(db_session)
    spent = await svc.spend(user_id=user.id, amount=30, service="image_generation")

    refund = await svc.refund(
        transaction_id=spent.transaction_id, reason="bug compensation"
    )
    assert refund.transaction_type == "refund"
    assert refund.new_balance == 100

    await db_session.refresh(user)
    assert user.token_balance == 100
    # total_tokens_spent rolled back
    assert user.total_tokens_spent == 0


@pytest.mark.asyncio
async def test_refund_of_purchase_rolls_back_total_purchased(db_session):
    user = await _make_user(db_session, telegram_id=8_000_012, code="TS-REF-2")
    svc = TokenService(db_session)
    purchase = await svc.add(
        user_id=user.id,
        amount=500,
        transaction_type="purchase",
        package_name="basic",
    )
    refund = await svc.refund(transaction_id=purchase.transaction_id)
    assert refund.new_balance == 0
    await db_session.refresh(user)
    assert user.total_tokens_purchased == 0


@pytest.mark.asyncio
async def test_refund_rejects_unknown_transaction(db_session):
    svc = TokenService(db_session)
    with pytest.raises(TransactionNotFoundError):
        await svc.refund(transaction_id=999_999_999)


@pytest.mark.asyncio
async def test_refund_rejects_non_refundable_transaction(db_session):
    user = await _make_user(db_session, telegram_id=8_000_013, code="TS-REF-3")
    svc = TokenService(db_session)
    bonus = await svc.add(user_id=user.id, amount=50, transaction_type="bonus")
    with pytest.raises(TransactionNotRefundableError):
        await svc.refund(transaction_id=bonus.transaction_id)


@pytest.mark.asyncio
async def test_refund_cannot_be_repeated(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_014, code="TS-REF-4", balance=100
    )
    svc = TokenService(db_session)
    spent = await svc.spend(user_id=user.id, amount=20, service="text_query")
    await svc.refund(transaction_id=spent.transaction_id)
    with pytest.raises(TransactionNotRefundableError):
        await svc.refund(transaction_id=spent.transaction_id)


# -------------------------------------------------------------------- audit


@pytest.mark.asyncio
async def test_reconcile_user_balance_detects_consistent_state(db_session):
    user = await _make_user(db_session, telegram_id=8_000_015, code="TS-REC-1")
    svc = TokenService(db_session)
    await svc.add(user_id=user.id, amount=100, transaction_type="bonus")
    await svc.spend(user_id=user.id, amount=40, service="text_query")
    audit = await reconcile_user_balance(db_session, user.id)
    assert audit.stored_balance == 60
    assert audit.computed_balance == 60
    assert audit.drift == 0
    assert audit.is_consistent


@pytest.mark.asyncio
async def test_reconcile_user_balance_detects_drift(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_016, code="TS-REC-2", balance=200
    )
    svc = TokenService(db_session)
    await svc.add(user_id=user.id, amount=50, transaction_type="bonus")
    audit = await reconcile_user_balance(db_session, user.id)
    # Stored balance is 250, but ledger only has 50 of credits → drift = 200.
    assert audit.stored_balance == 250
    assert audit.computed_balance == 50
    assert audit.drift == 200
    assert not audit.is_consistent


@pytest.mark.asyncio
async def test_reconcile_all_balances_returns_one_row_per_user(db_session):
    for i in range(3):
        await _make_user(
            db_session, telegram_id=8_100_000 + i, code=f"TS-REC-ALL-{i}"
        )
    audits = await reconcile_all_balances(db_session)
    # At least our 3 — there may be other users from earlier tests.
    assert len(audits) >= 3


@pytest.mark.asyncio
async def test_reconcile_unknown_user_raises(db_session):
    with pytest.raises(UserNotFoundError):
        await reconcile_user_balance(db_session, 123_456_789)


@pytest.mark.asyncio
async def test_reconcile_consistent_after_refund_of_spend(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_017, code="TS-REC-3", balance=100
    )
    svc = TokenService(db_session)
    spent = await svc.spend(user_id=user.id, amount=40, service="text_query")
    await svc.refund(transaction_id=spent.transaction_id)
    audit = await reconcile_user_balance(db_session, user.id)
    # Note: _make_user sets users.token_balance directly without a credit row,
    # so the ledger only knows about spend(-40) + refund-of-spend(+40) = 0.
    # The 100 starting balance is the drift between stored and ledger.
    assert audit.stored_balance == 100
    assert audit.computed_balance == 0
    assert audit.drift == 100


@pytest.mark.asyncio
async def test_reconcile_consistent_after_refund_of_purchase(db_session):
    user = await _make_user(
        db_session, telegram_id=8_000_018, code="TS-REC-4", balance=0
    )
    svc = TokenService(db_session)
    purchase = await svc.add(
        user_id=user.id,
        amount=500,
        transaction_type="purchase",
        package_name="basic",
    )
    await svc.refund(transaction_id=purchase.transaction_id)
    audit = await reconcile_user_balance(db_session, user.id)
    # purchase(+500) + refund-of-purchase(-500) = 0; stored is also 0.
    assert audit.stored_balance == 0
    assert audit.computed_balance == 0
    assert audit.is_consistent


# --------------------------------------------------------- concurrency smoke


@pytest.mark.asyncio
async def test_concurrent_spends_serialise_via_row_lock(db_engine):
    """Two concurrent spends on the same user must not double-spend.

    We open two real sessions on independent connections so the
    ``SELECT ... FOR UPDATE`` lock kicks in.  One should succeed, the
    other should raise :class:`InsufficientTokensError`.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(
        db_engine, expire_on_commit=False, class_=AsyncSession
    )

    # Seed a user we can spend against.  Use a dedicated session that we
    # commit so the concurrent transactions can see the row.
    async with factory() as setup:
        user = User(
            telegram_id=8_900_000,
            username="conc",
            referral_code="TS-CONC-1",
            token_balance=50,
        )
        setup.add(user)
        await setup.commit()
        user_id = user.id

    try:
        async def attempt() -> int | str:
            async with factory() as s:
                svc = TokenService(s)
                try:
                    res = await svc.spend(
                        user_id=user_id, amount=40, service="text_query"
                    )
                    await s.commit()
                    return res.new_balance
                except InsufficientTokensError:
                    await s.rollback()
                    return "insufficient"

        results = await asyncio.gather(attempt(), attempt())
        # One succeeds (balance=10), the other can't afford it.
        successes = [r for r in results if r == 10]
        failures = [r for r in results if r == "insufficient"]
        assert len(successes) == 1
        assert len(failures) == 1
    finally:
        async with factory() as cleanup:
            u = (
                await cleanup.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if u is not None:
                # Clean up transactions to satisfy the FK ON DELETE RESTRICT.
                await cleanup.execute(
                    Transaction.__table__.delete().where(
                        Transaction.user_id == user_id
                    )
                )
                await cleanup.delete(u)
                await cleanup.commit()
