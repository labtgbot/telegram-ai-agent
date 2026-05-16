"""User-facing token endpoints.

* ``GET /api/v1/user/balance`` — current token balance and premium status.
* ``GET /api/v1/user/usage-history`` — paginated debit history.
* ``GET /api/v1/user/referral`` — referral code, link and rewards summary.
* ``GET /api/v1/user/daily-bonus`` — claim status + streak preview.
* ``POST /api/v1/user/daily-bonus`` — credit today's bonus (idempotent per UTC day).

All endpoints require a valid ``X-Telegram-Init-Data`` header (handled by
:func:`app.auth.dependencies.get_current_user_from_init_data`).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import func, select

from app.auth.dependencies import SessionDep, get_current_user_from_init_data
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models.transaction import Transaction
from app.models.user import User
from app.services.daily_bonus import (
    AlreadyClaimedError,
    DailyBonusDisabledError,
    DailyBonusService,
)
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
    service = TokenService(session)
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
