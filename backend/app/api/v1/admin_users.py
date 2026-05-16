"""Admin User Management endpoints (Phase 3, issue #25).

All routes require an authenticated admin (``analyst`` or higher); ban,
unban, add-tokens and direct-message require ``support_admin`` or higher.
Every mutation writes an :class:`app.models.admin_audit_log.AdminAuditLog`
row in the same transaction, so a rolled-back request never leaves a
"phantom" log entry behind.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.api.v1.bot import BotClientDep
from app.auth.dependencies import SessionDep, get_current_admin
from app.auth.rbac import Role, require_role
from app.bot.client import TelegramApiError
from app.core.logging import get_logger
from app.models.admin_audit_log import AdminAuditLog
from app.models.transaction import Transaction
from app.models.user import User
from app.services.admin_users import (
    CannotTargetAdminError,
    CannotTargetSelfError,
    InvalidFilterError,
    MAX_MESSAGE_LEN,
    ServiceUsageRow,
    UserListFilters,
    UserNotFoundError,
    ban_user,
    export_users_csv,
    get_user_stats,
    list_audit_log,
    list_users,
    record_audit_event,
    unban_user,
)
from app.services.token_service import (
    InvalidAmountError,
    TokenService,
    UserNotFoundError as TokenUserNotFoundError,
)

router = APIRouter(prefix="/admin", tags=["admin-users"])
logger = get_logger(__name__)


# ---------------------------------------------------------------- response models


class AdminUserSummary(BaseModel):
    id: int
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    role: str
    is_premium: bool
    is_banned: bool
    ban_reason: str | None = None
    banned_until: datetime | None = None
    token_balance: int
    total_tokens_purchased: int
    total_tokens_spent: int
    total_requests: int
    referral_code: str
    referred_by: int | None = None
    created_at: datetime | None = None
    last_active_at: datetime | None = None
    last_login_at: datetime | None = None

    @classmethod
    def from_user(cls, user: User) -> AdminUserSummary:
        return cls(
            id=user.id,
            telegram_id=user.telegram_id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            language_code=user.language_code,
            role=user.role,
            is_premium=bool(user.is_premium),
            is_banned=bool(user.is_banned),
            ban_reason=user.ban_reason,
            banned_until=user.banned_until,
            token_balance=int(user.token_balance or 0),
            total_tokens_purchased=int(user.total_tokens_purchased or 0),
            total_tokens_spent=int(user.total_tokens_spent or 0),
            total_requests=int(user.total_requests or 0),
            referral_code=user.referral_code,
            referred_by=user.referred_by,
            created_at=user.created_at,
            last_active_at=user.last_active_at,
            last_login_at=user.last_login_at,
        )


class UserListResponse(BaseModel):
    items: list[AdminUserSummary]
    total: int
    page: int
    limit: int
    has_more: bool


class TransactionRow(BaseModel):
    id: int
    transaction_type: str
    tokens_amount: int
    stars_amount: int | None = None
    package_name: str | None = None
    payment_status: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @classmethod
    def from_tx(cls, tx: Transaction) -> TransactionRow:
        return cls(
            id=tx.id,
            transaction_type=tx.transaction_type,
            tokens_amount=int(tx.tokens_amount),
            stars_amount=tx.stars_amount,
            package_name=tx.package_name,
            payment_status=tx.payment_status,
            created_at=tx.created_at,
            completed_at=tx.completed_at,
        )


class ServiceUsageItem(BaseModel):
    service_type: str
    requests: int
    tokens_spent: int

    @classmethod
    def from_row(cls, row: ServiceUsageRow) -> ServiceUsageItem:
        return cls(
            service_type=row.service_type,
            requests=row.requests,
            tokens_spent=row.tokens_spent,
        )


class ReferralItem(BaseModel):
    user_id: int
    telegram_id: int
    username: str | None = None
    first_name: str | None = None
    is_premium: bool
    created_at: datetime


class UserStatsResponse(BaseModel):
    user: AdminUserSummary
    transactions_total: int
    recent_transactions: list[TransactionRow]
    services_usage: list[ServiceUsageItem]
    referrals_count: int
    recent_referrals: list[ReferralItem]


class AddTokensRequest(BaseModel):
    amount: int = Field(..., gt=0, le=1_000_000)
    reason: str = Field(..., min_length=1, max_length=200)


class AddTokensResponse(BaseModel):
    user_id: int
    amount: int
    new_balance: int
    transaction_id: int


class BanRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
    banned_until: datetime | None = None


class SendMessageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_MESSAGE_LEN)
    parse_mode: str | None = Field(default="HTML")
    disable_web_page_preview: bool = True


class SendMessageResponse(BaseModel):
    delivered: bool
    message_id: int | None = None


class AuditLogItem(BaseModel):
    id: int
    admin_id: int
    target_user_id: int | None = None
    action: str
    payload: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime

    @classmethod
    def from_row(cls, log: AdminAuditLog) -> AuditLogItem:
        return cls(
            id=log.id,
            admin_id=log.admin_id,
            target_user_id=log.target_user_id,
            action=log.action,
            payload=log.payload,
            ip_address=log.ip_address,
            user_agent=log.user_agent,
            created_at=log.created_at,
        )


class AuditLogResponse(BaseModel):
    items: list[AuditLogItem]
    total: int
    page: int
    limit: int
    has_more: bool


# ---------------------------------------------------------------- helpers


def _request_meta(request: Request) -> tuple[str | None, str | None]:
    ip = (
        request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else None)
    )
    return ip or None, request.headers.get("user-agent")


async def _commit_or_500(session: Any) -> None:
    try:
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        await session.rollback()
        logger.exception("admin.commit_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="commit_failed",
        ) from exc


# ---------------------------------------------------------------- endpoints


@router.get(
    "/users",
    response_model=UserListResponse,
    summary="List users with filters, sort and pagination",
)
async def list_users_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    search: Annotated[str | None, Query(max_length=200)] = None,
    is_premium: Annotated[bool | None, Query()] = None,
    is_banned: Annotated[bool | None, Query()] = None,
    role: Annotated[str | None, Query(max_length=32)] = None,
    referred_by: Annotated[int | None, Query()] = None,
    sort: Annotated[str, Query()] = "created_at",
    direction: Annotated[str, Query()] = "desc",
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> UserListResponse:
    filters = UserListFilters(
        search=search,
        is_premium=is_premium,
        is_banned=is_banned,
        role=role,
        referred_by=referred_by,
    )
    try:
        page_result = await list_users(
            session,
            filters=filters,
            sort=sort,  # type: ignore[arg-type]
            direction=direction,  # type: ignore[arg-type]
            page=page,
            limit=limit,
        )
    except InvalidFilterError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return UserListResponse(
        items=[AdminUserSummary.from_user(u) for u in page_result.items],
        total=page_result.total,
        page=page_result.page,
        limit=page_result.limit,
        has_more=page_result.has_more,
    )


@router.get(
    "/users/export.csv",
    response_class=PlainTextResponse,
    summary="Export users matching the given filters as CSV",
)
async def export_users_csv_endpoint(
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    search: Annotated[str | None, Query(max_length=200)] = None,
    is_premium: Annotated[bool | None, Query()] = None,
    is_banned: Annotated[bool | None, Query()] = None,
    role: Annotated[str | None, Query(max_length=32)] = None,
    referred_by: Annotated[int | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=50_000)] = 50_000,
) -> PlainTextResponse:
    filters = UserListFilters(
        search=search,
        is_premium=is_premium,
        is_banned=is_banned,
        role=role,
        referred_by=referred_by,
    )
    body = await export_users_csv(session, filters=filters, limit=limit)
    ip, ua = _request_meta(request)
    await record_audit_event(
        session,
        admin=admin,
        target_user_id=None,
        action="users.export_csv",
        payload={
            "search": search,
            "is_premium": is_premium,
            "is_banned": is_banned,
            "role": role,
            "limit": limit,
        },
        ip_address=ip,
        user_agent=ua,
    )
    await _commit_or_500(session)
    return PlainTextResponse(
        content=body,
        headers={
            "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="users.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "/users/{user_id}",
    response_model=AdminUserSummary,
    summary="Fetch a single user by id",
)
async def get_user_endpoint(
    user_id: int,
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
) -> AdminUserSummary:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        )
    return AdminUserSummary.from_user(user)


@router.get(
    "/users/{user_id}/stats",
    response_model=UserStatsResponse,
    summary="Full user detail: transactions, services usage, referrals",
)
async def get_user_stats_endpoint(
    user_id: int,
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
) -> UserStatsResponse:
    try:
        stats = await get_user_stats(session, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc

    return UserStatsResponse(
        user=AdminUserSummary.from_user(stats.user),
        transactions_total=stats.transactions_total,
        recent_transactions=[
            TransactionRow.from_tx(tx) for tx in stats.recent_transactions
        ],
        services_usage=[
            ServiceUsageItem.from_row(row) for row in stats.services_usage
        ],
        referrals_count=stats.referrals_count,
        recent_referrals=[
            ReferralItem(
                user_id=row.user_id,
                telegram_id=row.telegram_id,
                username=row.username,
                first_name=row.first_name,
                is_premium=row.is_premium,
                created_at=row.created_at,
            )
            for row in stats.recent_referrals
        ],
    )


@router.post(
    "/users/{user_id}/add-tokens",
    response_model=AddTokensResponse,
    summary="Manually credit tokens to a user as a bonus",
)
async def add_tokens_endpoint(
    user_id: int,
    payload: AddTokensRequest,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPPORT_ADMIN))],
) -> AddTokensResponse:
    service = TokenService(session)
    try:
        result = await service.manual_bonus(
            user_id=user_id,
            amount=payload.amount,
            reason=payload.reason,
            admin_id=admin.id,
        )
    except TokenUserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc
    except InvalidAmountError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    ip, ua = _request_meta(request)
    await record_audit_event(
        session,
        admin=admin,
        target_user_id=user_id,
        action="user.add_tokens",
        payload={
            "amount": payload.amount,
            "reason": payload.reason,
            "transaction_id": result.transaction_id,
            "new_balance": result.new_balance,
        },
        ip_address=ip,
        user_agent=ua,
    )
    await _commit_or_500(session)

    return AddTokensResponse(
        user_id=result.user_id,
        amount=result.amount,
        new_balance=result.new_balance,
        transaction_id=result.transaction_id,
    )


@router.post(
    "/users/{user_id}/ban",
    response_model=AdminUserSummary,
    summary="Ban a user (cannot ban admins or yourself)",
)
async def ban_user_endpoint(
    user_id: int,
    payload: BanRequest,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPPORT_ADMIN))],
) -> AdminUserSummary:
    ip, ua = _request_meta(request)
    try:
        user = await ban_user(
            session,
            admin=admin,
            user_id=user_id,
            reason=payload.reason,
            banned_until=payload.banned_until,
            ip_address=ip,
            user_agent=ua,
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc
    except CannotTargetSelfError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot_ban_self",
        ) from exc
    except CannotTargetAdminError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot_ban_admin",
        ) from exc

    await _commit_or_500(session)
    return AdminUserSummary.from_user(user)


@router.post(
    "/users/{user_id}/unban",
    response_model=AdminUserSummary,
    summary="Unban a user",
)
async def unban_user_endpoint(
    user_id: int,
    request: Request,
    session: SessionDep,
    admin: Annotated[User, Depends(require_role(Role.SUPPORT_ADMIN))],
) -> AdminUserSummary:
    ip, ua = _request_meta(request)
    try:
        user = await unban_user(
            session,
            admin=admin,
            user_id=user_id,
            ip_address=ip,
            user_agent=ua,
        )
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        ) from exc

    await _commit_or_500(session)
    return AdminUserSummary.from_user(user)


@router.post(
    "/users/{user_id}/message",
    response_model=SendMessageResponse,
    summary="Send a personal message to a user via the bot",
)
async def send_message_endpoint(
    user_id: int,
    payload: SendMessageRequest,
    request: Request,
    session: SessionDep,
    client: BotClientDep,
    admin: Annotated[User, Depends(require_role(Role.SUPPORT_ADMIN))],
) -> SendMessageResponse:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="user_not_found",
        )

    delivered = False
    message_id: int | None = None
    error_description: str | None = None
    try:
        result = await client.send_message(
            chat_id=user.telegram_id,
            text=payload.text,
            parse_mode=payload.parse_mode,
            disable_web_page_preview=payload.disable_web_page_preview,
        )
        delivered = True
        if isinstance(result, dict):
            mid = result.get("message_id")
            if isinstance(mid, int):
                message_id = mid
    except TelegramApiError as exc:
        error_description = exc.description

    ip, ua = _request_meta(request)
    await record_audit_event(
        session,
        admin=admin,
        target_user_id=user.id,
        action="user.send_message",
        payload={
            "telegram_id": user.telegram_id,
            "text_preview": payload.text[:200],
            "delivered": delivered,
            "message_id": message_id,
            "error": error_description,
        },
        ip_address=ip,
        user_agent=ua,
    )
    await _commit_or_500(session)

    if not delivered:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "telegram_send_failed",
                "description": error_description or "unknown error",
            },
        )

    return SendMessageResponse(delivered=True, message_id=message_id)


@router.get(
    "/audit-log",
    response_model=AuditLogResponse,
    summary="Paginated admin audit log (newest first)",
)
async def list_audit_log_endpoint(
    session: SessionDep,
    admin: Annotated[User, Depends(get_current_admin)],
    admin_id: Annotated[int | None, Query()] = None,
    target_user_id: Annotated[int | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
) -> AuditLogResponse:
    result = await list_audit_log(
        session,
        admin_id=admin_id,
        target_user_id=target_user_id,
        action=action,
        page=page,
        limit=limit,
    )
    return AuditLogResponse(
        items=[AuditLogItem.from_row(row) for row in result.items],
        total=result.total,
        page=result.page,
        limit=result.limit,
        has_more=result.has_more,
    )
