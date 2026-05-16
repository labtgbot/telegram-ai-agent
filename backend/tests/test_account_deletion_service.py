"""DB-backed tests for the GDPR Art. 17 account-deletion service.

Covers the happy path (request → cancel → re-request → worker anonymises)
plus the constraint guarantees that protect the user (only one pending
request, anonymise_user is idempotent, transactions are kept).

Skipped automatically when ``DATABASE_URL`` is not configured.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import (
    AccountDeletionRequest,
    ChatMessage,
    ChatThread,
    DailyBonusClaim,
    Transaction,
    User,
)
from app.models.account_deletion import (
    DELETION_STATUS_CANCELLED,
    DELETION_STATUS_COMPLETED,
    DELETION_STATUS_PENDING,
)
from app.services.account_deletion import (
    DEFAULT_GRACE_PERIOD_DAYS,
    DeletionAlreadyPendingError,
    NoPendingDeletionError,
    anonymise_user,
    cancel_account_deletion,
    get_deletion_status,
    get_pending_deletion,
    list_due_deletions,
    mark_deletion_completed,
    request_account_deletion,
)


async def _make_user(db_session, *, telegram_id: int, code: str) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"user_{telegram_id}",
        first_name="Alice",
        last_name="Smith",
        language_code="en",
        referral_code=code,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_request_creates_pending_with_30_day_window(db_session):
    user = await _make_user(db_session, telegram_id=900_001, code="GDPR-001")

    now = datetime(2026, 5, 16, 12, 0, 0, tzinfo=UTC)
    result = await request_account_deletion(
        db_session, user=user, now=now, requested_via="api"
    )
    assert result.status == DELETION_STATUS_PENDING
    assert result.scheduled_for == now + timedelta(days=DEFAULT_GRACE_PERIOD_DAYS)
    assert result.requested_at == now

    snapshot = await get_deletion_status(db_session, user.id)
    assert snapshot.pending is True
    assert snapshot.request_id == result.request_id


@pytest.mark.asyncio
async def test_second_request_is_rejected_while_pending(db_session):
    user = await _make_user(db_session, telegram_id=900_002, code="GDPR-002")
    await request_account_deletion(db_session, user=user)

    with pytest.raises(DeletionAlreadyPendingError) as exc_info:
        await request_account_deletion(db_session, user=user)
    assert exc_info.value.request.user_id == user.id
    assert exc_info.value.request.status == DELETION_STATUS_PENDING


@pytest.mark.asyncio
async def test_cancel_then_re_request_creates_new_row(db_session):
    user = await _make_user(db_session, telegram_id=900_003, code="GDPR-003")
    first = await request_account_deletion(db_session, user=user)

    snapshot = await cancel_account_deletion(db_session, user=user)
    assert snapshot.pending is False
    assert snapshot.request_id == first.request_id

    # No pending row → cancel should raise.
    with pytest.raises(NoPendingDeletionError):
        await cancel_account_deletion(db_session, user=user)

    # Re-requesting after cancellation is allowed.
    second = await request_account_deletion(db_session, user=user)
    assert second.request_id != first.request_id


@pytest.mark.asyncio
async def test_list_due_returns_only_expired_pending(db_session):
    user_a = await _make_user(db_session, telegram_id=900_010, code="GDPR-010")
    user_b = await _make_user(db_session, telegram_id=900_011, code="GDPR-011")

    past = datetime(2026, 1, 1, tzinfo=UTC)
    future = datetime(2026, 12, 1, tzinfo=UTC)
    db_session.add_all(
        [
            AccountDeletionRequest(
                user_id=user_a.id,
                status=DELETION_STATUS_PENDING,
                requested_at=past - timedelta(days=30),
                scheduled_for=past,
            ),
            AccountDeletionRequest(
                user_id=user_b.id,
                status=DELETION_STATUS_PENDING,
                requested_at=datetime(2026, 5, 16, tzinfo=UTC),
                scheduled_for=future,
            ),
        ]
    )
    await db_session.flush()

    cutoff = datetime(2026, 5, 16, tzinfo=UTC)
    due = await list_due_deletions(db_session, now=cutoff)
    due_user_ids = {row.user_id for row in due}
    assert user_a.id in due_user_ids
    assert user_b.id not in due_user_ids


@pytest.mark.asyncio
async def test_anonymise_user_clears_pii_and_keeps_transactions(db_session):
    user = await _make_user(db_session, telegram_id=900_020, code="GDPR-020")
    db_session.add(
        Transaction(
            user_id=user.id,
            transaction_type="purchase",
            tokens_amount=100,
            stars_amount=10,
            payment_status="completed",
        )
    )
    db_session.add(
        DailyBonusClaim(
            user_id=user.id, claim_date=datetime(2026, 5, 1).date(), streak_day=1, amount=5
        )
    )
    thread = ChatThread(user_id=user.id, external_id=12345)
    db_session.add(thread)
    await db_session.flush()
    db_session.add(
        ChatMessage(
            user_id=user.id,
            thread_id=thread.id,
            role="user",
            content="hello",
        )
    )
    await db_session.flush()

    changed = await anonymise_user(db_session, user_id=user.id)
    await db_session.flush()
    assert changed is True

    await db_session.refresh(user)
    assert user.username == f"deleted_user_{user.id}"
    assert user.first_name is None
    assert user.last_name is None
    assert user.language_code is None
    assert user.is_banned is True
    assert user.ban_reason == "account_deleted"

    # Transactions must be preserved for the accounting retention window.
    from sqlalchemy import select

    txs = (
        await db_session.execute(
            select(Transaction).where(Transaction.user_id == user.id)
        )
    ).scalars().all()
    assert len(txs) == 1

    chats = (
        await db_session.execute(
            select(ChatMessage).where(ChatMessage.user_id == user.id)
        )
    ).scalars().all()
    assert chats == []

    bonuses = (
        await db_session.execute(
            select(DailyBonusClaim).where(DailyBonusClaim.user_id == user.id)
        )
    ).scalars().all()
    assert bonuses == []


@pytest.mark.asyncio
async def test_anonymise_user_is_idempotent(db_session):
    user = await _make_user(db_session, telegram_id=900_021, code="GDPR-021")
    first = await anonymise_user(db_session, user_id=user.id)
    await db_session.flush()
    assert first is True

    second = await anonymise_user(db_session, user_id=user.id)
    await db_session.flush()
    assert second is False


@pytest.mark.asyncio
async def test_anonymise_detaches_referred_users(db_session):
    referrer = await _make_user(db_session, telegram_id=900_030, code="GDPR-030")
    referee = User(
        telegram_id=900_031,
        username="referee",
        referral_code="GDPR-031",
        referred_by=referrer.id,
    )
    db_session.add(referee)
    await db_session.flush()

    await anonymise_user(db_session, user_id=referrer.id)
    await db_session.flush()

    await db_session.refresh(referee)
    assert referee.referred_by is None


@pytest.mark.asyncio
async def test_mark_completed_flips_status(db_session):
    user = await _make_user(db_session, telegram_id=900_040, code="GDPR-040")
    result = await request_account_deletion(db_session, user=user)
    pending = await get_pending_deletion(db_session, user.id)
    assert pending is not None
    assert pending.id == result.request_id

    now = datetime(2026, 7, 1, tzinfo=UTC)
    await mark_deletion_completed(db_session, request=pending, now=now)
    await db_session.flush()
    assert pending.status == DELETION_STATUS_COMPLETED
    assert pending.completed_at == now


@pytest.mark.asyncio
async def test_cancel_records_cancelled_status(db_session):
    user = await _make_user(db_session, telegram_id=900_050, code="GDPR-050")
    requested = await request_account_deletion(db_session, user=user)
    await cancel_account_deletion(db_session, user=user)
    await db_session.flush()

    from sqlalchemy import select

    record = (
        await db_session.execute(
            select(AccountDeletionRequest).where(
                AccountDeletionRequest.id == requested.request_id
            )
        )
    ).scalar_one()
    assert record.status == DELETION_STATUS_CANCELLED
    assert record.cancelled_at is not None
