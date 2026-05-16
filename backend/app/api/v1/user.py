"""User-facing token endpoints.

* ``GET /api/v1/user/balance`` — current token balance and premium status.
* ``GET /api/v1/user/usage-history`` — paginated debit history.
* ``GET /api/v1/user/referral`` — referral code, link and rewards summary.

All endpoints require a valid ``X-Telegram-Init-Data`` header (handled by
:func:`app.auth.dependencies.get_current_user_from_init_data`).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.auth.dependencies import SessionDep, get_current_user_from_init_data
from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.transaction import Transaction
from app.models.user import User
from app.services.payments import REFERRAL_BONUS_PACKAGE
from app.services.token_service import TokenService, UserNotFoundError

router = APIRouter(prefix="/user", tags=["user"])
logger = get_logger(__name__)


_DAILY_BONUS_PACKAGE = "daily_bonus"


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


async def _daily_bonus_available(session: SessionDep, user_id: int) -> bool:
    """Return ``True`` if the user has not claimed a daily bonus today (UTC)."""
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    stmt = (
        select(Transaction.id)
        .where(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "bonus",
            Transaction.package_name == _DAILY_BONUS_PACKAGE,
            Transaction.created_at >= cutoff,
        )
        .limit(1)
    )
    last = (await session.execute(stmt)).scalar_one_or_none()
    return last is None


@router.get(
    "/balance",
    response_model=BalanceResponse,
    summary="Current token balance and premium status",
)
async def get_balance(
    session: SessionDep,
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
        daily_bonus_available=await _daily_bonus_available(session, user.id),
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
