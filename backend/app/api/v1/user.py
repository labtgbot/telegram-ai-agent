"""User-facing token endpoints.

* ``GET /api/v1/user/balance`` — current token balance and premium status.
* ``GET /api/v1/user/usage-history`` — paginated debit history.
* ``GET /api/v1/user/transactions`` — paginated ledger of every token
  movement (purchase / spend / bonus / refund / manual_bonus) with an
  optional ``type`` filter; used by the Mini App balance page history.
* ``GET /api/v1/user/referral`` — referral code + share link (Mini App).

All endpoints require a valid ``X-Telegram-Init-Data`` header (handled by
:func:`app.auth.dependencies.get_current_user_from_init_data`).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import (
    SessionDep,
    SettingsDep,
    get_current_user_from_init_data,
)
from app.core.logging import get_logger
from app.models.transaction import Transaction
from app.models.user import User
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


class ReferralResponse(BaseModel):
    referral_code: str
    referral_link: str
    bot_username: str | None = None
    start_param: str


@router.get(
    "/referral",
    response_model=ReferralResponse,
    summary="Referral code and shareable bot link for the current user",
)
async def get_referral(
    settings: SettingsDep,
    user: Annotated[User, Depends(get_current_user_from_init_data)],
) -> ReferralResponse:
    """Return the current user's referral code + shareable bot link.

    The link is built from ``settings.telegram_bot_username``; when the
    bot username is not configured (local dev), the link falls back to
    the bare ``start`` deep-link without the username so the UI can still
    show the code itself and let the user copy it.
    """
    bot_username = (settings.telegram_bot_username or "").strip().lstrip("@")
    code = user.referral_code
    start = f"ref_{code}"
    if bot_username:
        link = f"https://t.me/{bot_username}?start={start}"
    else:
        link = f"tg://resolve?start={start}"
    return ReferralResponse(
        referral_code=code,
        referral_link=link,
        bot_username=bot_username or None,
        start_param=start,
    )
