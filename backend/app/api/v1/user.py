"""User-facing token endpoints.

* ``GET /api/v1/user/balance`` — current token balance and premium status.
* ``GET /api/v1/user/usage-history`` — paginated debit history.
* ``GET /api/v1/user/transactions`` — paginated ledger of every token
  movement (purchase / spend / bonus / refund / manual_bonus) with an
  optional ``type`` filter; used by the Mini App balance page history.
* ``GET /api/v1/user/referral`` — referral code, link and rewards summary.
* ``GET /api/v1/user/daily-bonus`` — claim status + streak preview.
* ``POST /api/v1/user/daily-bonus`` — credit today's bonus (idempotent per UTC day).
* ``GET /api/v1/user/me/export`` — GDPR Art. 15/20 data export (JSON).
* ``DELETE /api/v1/user/me`` — schedule GDPR Art. 17 anonymisation
  (30-day grace period).
* ``POST /api/v1/user/me/cancel-deletion`` — cancel a pending deletion.
* ``GET /api/v1/user/me/deletion-status`` — status of the deletion grace
  period (used by the Mini App banner).

All endpoints require a valid ``X-Telegram-Init-Data`` header (handled by
:func:`app.auth.dependencies.get_current_user_from_init_data`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import SessionDep, get_current_user_from_init_data
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models.transaction import Transaction
from app.models.user import User
from app.services.account_deletion import (
    DeletionAlreadyPendingError,
    NoPendingDeletionError,
    cancel_account_deletion,
    get_deletion_status,
    request_account_deletion,
)
from app.services.balance_cache import get_default_balance_cache
from app.services.daily_bonus import (
    AlreadyClaimedError,
    DailyBonusDisabledError,
    DailyBonusService,
)
from app.services.data_export import build_user_data_export
from app.services.payments import REFERRAL_BONUS_PACKAGE
from app.services.token_service import TokenService, UserNotFoundError

router = APIRouter(prefix="/user", tags=["user"])
logger = get_logger(__name__)


def _redis_dep() -> Redis:
    return get_redis()


RedisDep = Annotated[Redis, Depends(_redis_dep)]


class BalanceResponse(BaseModel):
    token_balance: int
    is_premium: bool
    premium_expires_at: datetime | None = None
    daily_bonus_available: bool


class UsageHistoryItem(BaseModel):
    id: int
    service_type: str
    tokens_consumed: int
    response_status: str | None = None
    processing_time_ms: int | None = None
    request_params: dict[str, Any] | None = None
    created_at: datetime


class UsageHistoryResponse(BaseModel):
    items: list[UsageHistoryItem]
    total: int
    page: int
    limit: int
    has_more: bool


class ReferralResponse(BaseModel):
    referral_code: str
    referrals_count: int
    bonus_tokens_earned: int
    referral_link: str


class DailyBonusStatusResponse(BaseModel):
    """Snapshot of the user's daily-bonus state for the claim card."""

    available: bool
    enabled: bool
    streak_day: int
    next_amount: int
    last_claim_date: date | None = None
    next_available_at: datetime
    amounts: list[int]


class DailyBonusClaimResponse(BaseModel):
    """Successful daily-bonus credit — mirrors the service result."""

    amount: int
    streak_day: int
    new_balance: int
    transaction_id: int
    claim_date: date
    next_available_at: datetime


def _build_referral_link(bot_username: str, referral_code: str) -> str:
    if not bot_username:
        return f"start=REF:{referral_code}"
    return f"https://t.me/{bot_username}?start={referral_code}"


async def _count_referrals(session: SessionDep, user_id: int) -> int:
    """Number of users that joined via ``user_id``'s referral code."""
    total = await session.scalar(
        select(func.count())
        .select_from(User)
        .where(User.referred_by == user_id)
    )
    return int(total or 0)


async def _sum_referral_bonus(session: SessionDep, user_id: int) -> int:
    """Sum of tokens credited to ``user_id`` as referral bonuses."""
    total = await session.scalar(
        select(func.coalesce(func.sum(Transaction.tokens_amount), 0)).where(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "bonus",
            Transaction.package_name == REFERRAL_BONUS_PACKAGE,
            Transaction.payment_status == "completed",
        )
    )
    return int(total or 0)


async def _daily_bonus_available(
    session: SessionDep, redis: Redis, user_id: int
) -> bool:
    """Return ``True`` if the user can claim a daily bonus right now (UTC day)."""
    service = DailyBonusService(session, redis)
    status_ = await service.status(user_id)
    return status_.available


@router.get(
    "/balance",
    response_model=BalanceResponse,
    summary="Current token balance and premium status",
)
async def get_balance(
    session: SessionDep,
    redis: RedisDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> BalanceResponse:
    service = TokenService(session, get_default_balance_cache())
    try:
        balance = await service.get_balance(user.id)
    except UserNotFoundError:
        balance = int(user.token_balance or 0)
    return BalanceResponse(
        token_balance=balance,
        is_premium=bool(user.is_premium),
        premium_expires_at=user.premium_expires_at,
        daily_bonus_available=await _daily_bonus_available(session, redis, user.id),
    )


@router.get(
    "/usage-history",
    response_model=UsageHistoryResponse,
    summary="Paginated token-spend history",
)
async def get_usage_history(
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> UsageHistoryResponse:
    service = TokenService(session)
    history = await service.usage_history(user.id, page=page, limit=limit)
    items = [
        UsageHistoryItem(
            id=row.id,
            service_type=row.service_type,
            tokens_consumed=row.tokens_consumed,
            response_status=row.response_status,
            processing_time_ms=row.processing_time_ms,
            request_params=row.request_params,
            created_at=row.created_at,
        )
        for row in history.items
    ]
    return UsageHistoryResponse(
        items=items,
        total=history.total,
        page=history.page,
        limit=history.limit,
        has_more=history.has_more,
    )


class TransactionItem(BaseModel):
    id: int
    transaction_type: str
    tokens_amount: int
    stars_amount: int | None = None
    package_name: str | None = None
    payment_status: str | None = None
    payment_method: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class TransactionsResponse(BaseModel):
    items: list[TransactionItem]
    total: int
    page: int
    limit: int
    has_more: bool


_ALLOWED_TX_TYPES: frozenset[str] = frozenset(
    {"purchase", "spend", "bonus", "refund", "manual_bonus"}
)


@dataclass(frozen=True)
class _TransactionsPage:
    """Internal page wrapper so the endpoint can be unit-tested via a stub."""

    items: list[Transaction]
    total: int
    page: int
    limit: int


async def _list_transactions(
    session: AsyncSession,
    *,
    user_id: int,
    page: int,
    limit: int,
    transaction_type: str | None,
) -> _TransactionsPage:
    """Run the transactions query.  Extracted from the route handler so the
    Mini App test suite can swap it with an in-memory fake without needing
    a real database."""
    offset = (page - 1) * limit
    where = [Transaction.user_id == user_id]
    if transaction_type and transaction_type in _ALLOWED_TX_TYPES:
        where.append(Transaction.transaction_type == transaction_type)

    total_stmt = select(func.count()).select_from(Transaction).where(*where)
    total = int((await session.execute(total_stmt)).scalar_one())

    items_stmt = (
        select(Transaction)
        .where(*where)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await session.execute(items_stmt)).scalars().all())
    return _TransactionsPage(items=rows, total=total, page=page, limit=limit)


@router.get(
    "/transactions",
    response_model=TransactionsResponse,
    summary="Paginated transaction ledger (purchases, bonuses, spends, refunds)",
)
async def get_transactions(
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    transaction_type: Annotated[
        str | None,
        Query(
            alias="type",
            description=(
                "Filter by transaction type. One of: "
                "purchase, spend, bonus, refund, manual_bonus."
            ),
        ),
    ] = None,
) -> TransactionsResponse:
    """Return a paginated slice of the user's transactions ledger.

    The Mini App balance page uses this to render purchase history and
    bonus / refund timelines.  ``type`` is optional and accepts any of
    the values listed in :data:`_ALLOWED_TX_TYPES`; unknown values are
    silently ignored so the UI may always submit its currently selected
    filter without first validating against the catalog.
    """
    result = await _list_transactions(
        session,
        user_id=user.id,
        page=page,
        limit=limit,
        transaction_type=transaction_type,
    )
    items = [
        TransactionItem(
            id=row.id,
            transaction_type=row.transaction_type,
            tokens_amount=row.tokens_amount,
            stars_amount=row.stars_amount,
            package_name=row.package_name,
            payment_status=row.payment_status,
            payment_method=row.payment_method,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )
        for row in result.items
    ]
    return TransactionsResponse(
        items=items,
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_more=(result.page * result.limit) < result.total,
    )


@router.get(
    "/referral",
    response_model=ReferralResponse,
    summary="Referral code, share link and reward summary",
)
async def get_referral(
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> ReferralResponse:
    referrals_count = await _count_referrals(session, user.id)
    bonus_earned = await _sum_referral_bonus(session, user.id)
    settings = get_settings()
    return ReferralResponse(
        referral_code=user.referral_code,
        referrals_count=referrals_count,
        bonus_tokens_earned=bonus_earned,
        referral_link=_build_referral_link(
            settings.telegram_bot_username,
            user.referral_code,
        ),
    )


@router.get(
    "/daily-bonus",
    response_model=DailyBonusStatusResponse,
    summary="Daily-bonus claim status and streak preview",
)
async def get_daily_bonus_status(
    session: SessionDep,
    redis: RedisDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> DailyBonusStatusResponse:
    service = DailyBonusService(session, redis)
    snapshot = await service.status(user.id)
    return DailyBonusStatusResponse(
        available=snapshot.available,
        enabled=snapshot.enabled,
        streak_day=snapshot.streak_day,
        next_amount=snapshot.next_amount,
        last_claim_date=snapshot.last_claim_date,
        next_available_at=snapshot.next_available_at,
        amounts=list(snapshot.amounts),
    )


@router.post(
    "/daily-bonus",
    response_model=DailyBonusClaimResponse,
    summary="Claim today's daily bonus (UTC; once per day per user)",
)
async def claim_daily_bonus(
    session: SessionDep,
    redis: RedisDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> DailyBonusClaimResponse:
    service = DailyBonusService(session, redis)
    try:
        result = await service.claim(user.id)
    except AlreadyClaimedError as exc:
        # 409 — same UTC day; surface the wall-clock the client can use
        # to disable the button until midnight UTC.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "daily_bonus_already_claimed",
                "next_available_at": exc.next_available_at.isoformat(),
            },
        ) from exc
    except DailyBonusDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="daily_bonus_disabled",
        ) from exc
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001 — surface a clean 500
        await session.rollback()
        logger.exception("daily_bonus.commit_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return DailyBonusClaimResponse(
        amount=result.amount,
        streak_day=result.streak_day,
        new_balance=result.new_balance,
        transaction_id=result.transaction_id,
        claim_date=result.claim_date,
        next_available_at=result.next_available_at,
    )


# ---------------------------------------------------------------- GDPR rights


class DataExportResponse(BaseModel):
    """Result of GDPR Art. 15 / Art. 20 user data export."""

    schema_version: str
    generated_at: datetime
    user: dict[str, Any]
    transactions: list[dict[str, Any]]
    subscriptions: list[dict[str, Any]]
    chat_threads: list[dict[str, Any]]
    chat_messages: list[dict[str, Any]]
    daily_bonus_claims: list[dict[str, Any]]
    referrals_summary: dict[str, int]
    notes: list[str]


class DeletionStatusResponse(BaseModel):
    pending: bool
    request_id: int | None = None
    requested_at: datetime | None = None
    scheduled_for: datetime | None = None


class DeleteAccountResponse(BaseModel):
    request_id: int
    status: str
    requested_at: datetime
    scheduled_for: datetime
    detail: str = "deletion_scheduled"


class CancelDeletionResponse(BaseModel):
    cancelled: bool
    request_id: int | None = None


@router.get(
    "/me/export",
    response_model=DataExportResponse,
    summary="GDPR Art. 15 / Art. 20 — download your data (JSON)",
)
async def export_my_data(
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> DataExportResponse:
    export = await build_user_data_export(session, user=user)
    payload = export.to_json()
    logger.info(
        "user.data_export",
        user_id=user.id,
        transactions=len(export.transactions),
        chat_messages=len(export.chat_messages),
        notes=len(export.notes),
    )
    return DataExportResponse(**payload)


@router.get(
    "/me/deletion-status",
    response_model=DeletionStatusResponse,
    summary="Current account-deletion grace-period status",
)
async def my_deletion_status(
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> DeletionStatusResponse:
    snapshot = await get_deletion_status(session, user.id)
    return DeletionStatusResponse(
        pending=snapshot.pending,
        request_id=snapshot.request_id,
        requested_at=snapshot.requested_at,
        scheduled_for=snapshot.scheduled_for,
    )


@router.delete(
    "/me",
    response_model=DeleteAccountResponse,
    summary="GDPR Art. 17 — schedule account anonymisation (30-day grace)",
    status_code=status.HTTP_202_ACCEPTED,
)
async def delete_my_account(
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> DeleteAccountResponse:
    try:
        result = await request_account_deletion(
            session,
            user=user,
            requested_via="mini_app",
        )
    except DeletionAlreadyPendingError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "deletion_already_pending",
                "request_id": exc.request.id,
                "scheduled_for": exc.request.scheduled_for.isoformat(),
            },
        ) from exc

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("user.delete_me.commit_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return DeleteAccountResponse(
        request_id=result.request_id,
        status=result.status,
        requested_at=result.requested_at,
        scheduled_for=result.scheduled_for,
    )


@router.post(
    "/me/cancel-deletion",
    response_model=CancelDeletionResponse,
    summary="Cancel a pending account-deletion request",
)
async def cancel_my_account_deletion(
    session: SessionDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> CancelDeletionResponse:
    try:
        snapshot = await cancel_account_deletion(session, user=user)
    except NoPendingDeletionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no_pending_deletion",
        ) from exc

    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("user.cancel_deletion.commit_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc

    return CancelDeletionResponse(cancelled=True, request_id=snapshot.request_id)
