"""Admin-facing user management service.

Powers the CRM "Users" section: filtered/sorted/paginated listing, per-user
stats, ban / unban, manual token grants and direct messages from the bot.
Every mutation goes through :func:`record_audit_event` so support engineers
always have a tamper-evident "who did what, when" trail.

The service is intentionally split into small functions rather than a
class — they're trivially unit-testable and the API layer can compose
them without bringing the entire surface area in scope.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

from sqlalchemy import Select, and_, asc, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role
from app.core.logging import get_logger
from app.models.admin_audit_log import AdminAuditLog
from app.models.token_usage_log import TokenUsageLog
from app.models.transaction import Transaction
from app.models.user import User

logger = get_logger(__name__)


# ----------------------------------------------------------------- constants


SortField = Literal[
    "created_at",
    "last_active_at",
    "token_balance",
    "total_tokens_spent",
    "total_requests",
    "telegram_id",
]
SortDirection = Literal["asc", "desc"]

ALLOWED_SORT_FIELDS: frozenset[str] = frozenset(
    {
        "created_at",
        "last_active_at",
        "token_balance",
        "total_tokens_spent",
        "total_requests",
        "telegram_id",
    }
)

DEFAULT_LIMIT = 25
MAX_LIMIT = 200
MAX_CSV_ROWS = 50_000
MAX_BAN_REASON_LEN = 500
MAX_MESSAGE_LEN = 4096


# ----------------------------------------------------------------- exceptions


class AdminUsersError(Exception):
    """Base class for admin-users service failures."""


class UserNotFoundError(AdminUsersError):
    """The referenced user does not exist."""


class InvalidFilterError(AdminUsersError):
    """A filter / sort parameter is malformed."""


class CannotTargetSelfError(AdminUsersError):
    """An admin tried to mutate their own account in a destructive way."""


class CannotTargetAdminError(AdminUsersError):
    """An admin tried to ban another admin (support-admin or super-admin)."""


# ---------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class UserListFilters:
    """Filters accepted by :func:`list_users`.

    All fields are optional; an empty object lists every user.  ``search``
    matches on ``username`` (case-insensitive prefix) or ``telegram_id``
    (exact); the API layer normalises whatever the operator typed.
    """

    search: str | None = None
    is_premium: bool | None = None
    is_banned: bool | None = None
    role: str | None = None
    referred_by: int | None = None


@dataclass(frozen=True)
class UserListPage:
    items: list[User]
    total: int
    page: int
    limit: int
    has_more: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "has_more", (self.page * self.limit) < self.total
        )


@dataclass(frozen=True)
class ServiceUsageRow:
    service_type: str
    requests: int
    tokens_spent: int


@dataclass(frozen=True)
class ReferralRow:
    user_id: int
    telegram_id: int
    username: str | None
    first_name: str | None
    is_premium: bool
    created_at: datetime


@dataclass(frozen=True)
class UserStats:
    user: User
    transactions_total: int
    recent_transactions: list[Transaction]
    services_usage: list[ServiceUsageRow]
    referrals_count: int
    recent_referrals: list[ReferralRow]


# ------------------------------------------------------------------ listing


def _coerce_search(value: str | None) -> tuple[str | None, int | None]:
    """Split free-form search into (username_prefix, telegram_id)."""
    if not value:
        return None, None
    raw = value.strip()
    if not raw:
        return None, None
    if raw.startswith("@"):
        stripped = raw[1:].strip()
        return (stripped.lower() if stripped else None), None
    if raw.lstrip("-").isdigit():
        try:
            return None, int(raw)
        except ValueError:
            return raw.lower(), None
    return raw.lower(), None


def _apply_filters(stmt: Select[Any], filters: UserListFilters) -> Select[Any]:
    username_prefix, telegram_id = _coerce_search(filters.search)
    if username_prefix and telegram_id is None:
        like = f"{username_prefix}%"
        stmt = stmt.where(
            or_(
                func.lower(User.username).like(like),
                func.lower(User.first_name).like(like),
                func.lower(User.last_name).like(like),
            )
        )
    if telegram_id is not None:
        stmt = stmt.where(User.telegram_id == telegram_id)
    if filters.is_premium is not None:
        stmt = stmt.where(User.is_premium.is_(filters.is_premium))
    if filters.is_banned is not None:
        stmt = stmt.where(User.is_banned.is_(filters.is_banned))
    if filters.role:
        stmt = stmt.where(User.role == filters.role)
    if filters.referred_by is not None:
        stmt = stmt.where(User.referred_by == filters.referred_by)
    return stmt


def _coerce_sort(field_: str, direction: str) -> tuple[SortField, SortDirection]:
    if field_ not in ALLOWED_SORT_FIELDS:
        raise InvalidFilterError(f"unsupported sort field: {field_}")
    if direction not in ("asc", "desc"):
        raise InvalidFilterError(f"unsupported sort direction: {direction}")
    return cast(SortField, field_), cast(SortDirection, direction)


async def list_users(
    session: AsyncSession,
    *,
    filters: UserListFilters | None = None,
    sort: SortField = "created_at",
    direction: SortDirection = "desc",
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
) -> UserListPage:
    """Return a paginated list of users matching ``filters``."""
    filters = filters or UserListFilters()
    sort_field, sort_direction = _coerce_sort(sort, direction)

    page = max(int(page or 1), 1)
    limit = max(min(int(limit or DEFAULT_LIMIT), MAX_LIMIT), 1)
    offset = (page - 1) * limit

    count_stmt = _apply_filters(select(func.count(User.id)), filters)
    total = int((await session.execute(count_stmt)).scalar_one())

    order_col = getattr(User, sort_field)
    order_clause = desc(order_col) if sort_direction == "desc" else asc(order_col)

    rows_stmt = (
        _apply_filters(select(User), filters)
        .order_by(order_clause, User.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = list((await session.execute(rows_stmt)).scalars().all())
    return UserListPage(items=rows, total=total, page=page, limit=limit)


# ------------------------------------------------------------------- stats


async def _load_user_or_raise(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise UserNotFoundError(f"user {user_id} not found")
    return user


async def get_user_stats(
    session: AsyncSession,
    user_id: int,
    *,
    recent_transactions_limit: int = 20,
    recent_referrals_limit: int = 20,
) -> UserStats:
    """Aggregate everything the admin UI shows on the user detail card."""
    user = await _load_user_or_raise(session, user_id)

    tx_total_stmt = (
        select(func.count())
        .select_from(Transaction)
        .where(Transaction.user_id == user_id)
    )
    tx_total = int((await session.execute(tx_total_stmt)).scalar_one())

    tx_recent_stmt = (
        select(Transaction)
        .where(Transaction.user_id == user_id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(recent_transactions_limit)
    )
    recent_transactions = list(
        (await session.execute(tx_recent_stmt)).scalars().all()
    )

    usage_stmt = (
        select(
            TokenUsageLog.service_type,
            func.count().label("requests"),
            func.coalesce(func.sum(TokenUsageLog.tokens_consumed), 0).label(
                "tokens_spent"
            ),
        )
        .where(TokenUsageLog.user_id == user_id)
        .group_by(TokenUsageLog.service_type)
        .order_by(func.sum(TokenUsageLog.tokens_consumed).desc())
    )
    services_usage = [
        ServiceUsageRow(
            service_type=row.service_type,
            requests=int(row.requests),
            tokens_spent=int(row.tokens_spent),
        )
        for row in (await session.execute(usage_stmt)).all()
    ]

    referrals_count_stmt = (
        select(func.count())
        .select_from(User)
        .where(User.referred_by == user_id)
    )
    referrals_count = int(
        (await session.execute(referrals_count_stmt)).scalar_one()
    )

    referrals_stmt = (
        select(User)
        .where(User.referred_by == user_id)
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(recent_referrals_limit)
    )
    recent_referrals = [
        ReferralRow(
            user_id=row.id,
            telegram_id=row.telegram_id,
            username=row.username,
            first_name=row.first_name,
            is_premium=bool(row.is_premium),
            created_at=row.created_at,
        )
        for row in (await session.execute(referrals_stmt)).scalars().all()
    ]

    return UserStats(
        user=user,
        transactions_total=tx_total,
        recent_transactions=recent_transactions,
        services_usage=services_usage,
        referrals_count=referrals_count,
        recent_referrals=recent_referrals,
    )


# ------------------------------------------------------------------- bans


async def ban_user(
    session: AsyncSession,
    *,
    admin: User,
    user_id: int,
    reason: str | None = None,
    banned_until: datetime | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> User:
    """Mark ``user_id`` as banned.  Refuses to ban admins or oneself."""
    if user_id == admin.id:
        raise CannotTargetSelfError("admins cannot ban themselves")

    user = await _load_user_or_raise(session, user_id)
    actual_role = Role.coerce(user.role)
    if actual_role in (Role.SUPPORT_ADMIN, Role.SUPER_ADMIN):
        raise CannotTargetAdminError(
            f"cannot ban a user holding role={user.role!r}"
        )

    user.is_banned = True
    if reason:
        user.ban_reason = reason.strip()[:MAX_BAN_REASON_LEN]
    user.banned_until = banned_until
    await session.flush()

    await record_audit_event(
        session,
        admin=admin,
        target_user_id=user.id,
        action="user.ban",
        payload={
            "reason": user.ban_reason,
            "banned_until": banned_until.isoformat() if banned_until else None,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return user


async def unban_user(
    session: AsyncSession,
    *,
    admin: User,
    user_id: int,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> User:
    """Clear ``is_banned`` and reset ban metadata for ``user_id``."""
    user = await _load_user_or_raise(session, user_id)
    user.is_banned = False
    user.ban_reason = None
    user.banned_until = None
    await session.flush()

    await record_audit_event(
        session,
        admin=admin,
        target_user_id=user.id,
        action="user.unban",
        payload=None,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return user


# ----------------------------------------------------------------- audit log


async def record_audit_event(
    session: AsyncSession,
    *,
    admin: User,
    target_user_id: int | None,
    action: str,
    payload: dict[str, Any] | None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> AdminAuditLog:
    """Append a row to ``admin_audit_logs``.

    The caller is responsible for committing the transaction; this only
    flushes so callers can roll back the entire action on error.
    """
    if not action or not action.strip():
        raise InvalidFilterError("action is required")

    log = AdminAuditLog(
        admin_id=admin.id,
        target_user_id=target_user_id,
        action=action.strip()[:64],
        payload=payload,
        ip_address=(ip_address or "")[:64] or None,
        user_agent=(user_agent or "")[:512] or None,
    )
    session.add(log)
    await session.flush()
    logger.info(
        "admin.audit",
        admin_id=admin.id,
        target_user_id=target_user_id,
        action=log.action,
        log_id=log.id,
    )
    return log


@dataclass(frozen=True)
class AuditLogPage:
    items: list[AdminAuditLog]
    total: int
    page: int
    limit: int
    has_more: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "has_more", (self.page * self.limit) < self.total
        )


async def list_audit_log(
    session: AsyncSession,
    *,
    admin_id: int | None = None,
    target_user_id: int | None = None,
    action: str | None = None,
    page: int = 1,
    limit: int = DEFAULT_LIMIT,
) -> AuditLogPage:
    """Paginated view over the admin audit log, newest first."""
    page = max(int(page or 1), 1)
    limit = max(min(int(limit or DEFAULT_LIMIT), MAX_LIMIT), 1)
    offset = (page - 1) * limit

    conditions = []
    if admin_id is not None:
        conditions.append(AdminAuditLog.admin_id == admin_id)
    if target_user_id is not None:
        conditions.append(AdminAuditLog.target_user_id == target_user_id)
    if action:
        conditions.append(AdminAuditLog.action == action.strip())

    count_stmt = select(func.count()).select_from(AdminAuditLog)
    rows_stmt = select(AdminAuditLog)
    if conditions:
        where = and_(*conditions)
        count_stmt = count_stmt.where(where)
        rows_stmt = rows_stmt.where(where)
    rows_stmt = (
        rows_stmt.order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
        .offset(offset)
        .limit(limit)
    )

    total = int((await session.execute(count_stmt)).scalar_one())
    items = list((await session.execute(rows_stmt)).scalars().all())
    return AuditLogPage(items=items, total=total, page=page, limit=limit)


# ----------------------------------------------------------------- CSV export


CSV_COLUMNS: tuple[str, ...] = (
    "id",
    "telegram_id",
    "username",
    "first_name",
    "last_name",
    "language_code",
    "role",
    "is_premium",
    "is_banned",
    "token_balance",
    "total_tokens_purchased",
    "total_tokens_spent",
    "total_requests",
    "referral_code",
    "referred_by",
    "created_at",
    "last_active_at",
)


def _csv_row(user: User) -> list[str]:
    def _fmt(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat() if value.tzinfo else value.isoformat()
        return str(value)

    return [_fmt(getattr(user, column)) for column in CSV_COLUMNS]


async def export_users_csv(
    session: AsyncSession,
    *,
    filters: UserListFilters | None = None,
    limit: int = MAX_CSV_ROWS,
) -> str:
    """Render filtered users as a CSV string.

    Bounded to :data:`MAX_CSV_ROWS` (50k) to keep response sizes finite.
    """
    filters = filters or UserListFilters()
    limit = max(min(int(limit or MAX_CSV_ROWS), MAX_CSV_ROWS), 1)
    stmt = (
        _apply_filters(select(User), filters)
        .order_by(User.id.asc())
        .limit(limit)
    )
    rows = list((await session.execute(stmt)).scalars().all())

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_COLUMNS)
    for user in rows:
        writer.writerow(_csv_row(user))
    return buffer.getvalue()
