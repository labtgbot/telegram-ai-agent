"""GDPR Art. 15 / Art. 20 — user data access & portability.

Builds a JSON dump of everything the Service stores for a single user. The
shape is stable on purpose: external tooling (Mini App download link,
support scripts, dump diff tests) consumes it directly.

Each section is queried independently so a slow / missing table degrades
the export gracefully instead of failing the whole request. We never
include other users' data (e.g. people referred by this user are summarised
by anonymised count, not enumerated).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.chat_history import ChatMessage, ChatThread
from app.models.daily_bonus_claim import DailyBonusClaim
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.models.user import User

logger = get_logger(__name__)

EXPORT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class UserDataExport:
    """Result returned by :func:`build_user_data_export`."""

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

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at.isoformat(),
            "user": self.user,
            "transactions": self.transactions,
            "subscriptions": self.subscriptions,
            "chat_threads": self.chat_threads,
            "chat_messages": self.chat_messages,
            "daily_bonus_claims": self.daily_bonus_claims,
            "referrals_summary": self.referrals_summary,
            "notes": self.notes,
        }


def _serialise(value: Any) -> Any:
    """Convert SQLAlchemy column values into JSON-friendly primitives."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _user_to_dict(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "language_code": user.language_code,
        "referral_code": user.referral_code,
        "referred_by": user.referred_by,
        "token_balance": user.token_balance,
        "total_tokens_purchased": user.total_tokens_purchased,
        "total_tokens_spent": user.total_tokens_spent,
        "total_requests": user.total_requests,
        "is_premium": user.is_premium,
        "premium_expires_at": _serialise(user.premium_expires_at),
        "role": user.role,
        "created_at": _serialise(user.created_at),
        "last_active_at": _serialise(user.last_active_at),
        "last_login_at": _serialise(user.last_login_at),
    }


def _transaction_to_dict(row: Transaction) -> dict[str, Any]:
    return {
        "id": row.id,
        "transaction_type": row.transaction_type,
        "tokens_amount": row.tokens_amount,
        "stars_amount": row.stars_amount,
        "usd_amount": _serialise(row.usd_amount),
        "package_name": row.package_name,
        "discount_percent": row.discount_percent,
        "payment_status": row.payment_status,
        "payment_method": row.payment_method,
        "created_at": _serialise(row.created_at),
        "completed_at": _serialise(row.completed_at),
    }


def _subscription_to_dict(row: Subscription) -> dict[str, Any]:
    return {
        "id": row.id,
        "plan_code": row.plan_code,
        "starts_at": _serialise(row.starts_at),
        "expires_at": _serialise(row.expires_at),
        "auto_renew": row.auto_renew,
        "status": row.status,
    }


def _chat_thread_to_dict(row: ChatThread) -> dict[str, Any]:
    return {
        "id": row.id,
        "external_id": row.external_id,
        "title": row.title,
        "mode": row.mode,
        "system_prompt": row.system_prompt,
        "message_count": row.message_count,
        "last_message_at": _serialise(row.last_message_at),
        "created_at": _serialise(row.created_at),
    }


def _chat_message_to_dict(row: ChatMessage) -> dict[str, Any]:
    return {
        "id": row.id,
        "thread_id": row.thread_id,
        "role": row.role,
        "content": row.content,
        "tokens_consumed": row.tokens_consumed,
        "composio_tool": row.composio_tool,
        "metadata": row.metadata_json,
        "created_at": _serialise(row.created_at),
    }


def _daily_bonus_claim_to_dict(row: DailyBonusClaim) -> dict[str, Any]:
    return {
        "claim_date": _serialise(row.claim_date),
        "streak_day": row.streak_day,
        "amount": row.amount,
        "created_at": _serialise(row.created_at),
    }


async def _safe_select(
    session: AsyncSession,
    stmt: Any,
    *,
    notes: list[str],
    note_tag: str,
) -> list[Any]:
    """Run a SELECT and degrade gracefully on errors.

    The export must never fail entirely just because (say) a partition table
    is unavailable. We record the issue in ``notes`` so the user knows what
    is missing.
    """
    try:
        result = await session.execute(stmt)
        return list(result.scalars().all())
    except SQLAlchemyError as exc:
        logger.warning(
            "data_export.section_failed", section=note_tag, error=str(exc)
        )
        notes.append(f"{note_tag}: unavailable ({type(exc).__name__})")
        return []


async def build_user_data_export(
    session: AsyncSession,
    *,
    user: User,
    max_chat_messages: int = 10_000,
) -> UserDataExport:
    """Assemble the full export for ``user``.

    Args:
        session: an active async session.
        user: the user whose data we are exporting (already authenticated).
        max_chat_messages: safety cap so a runaway chat history does not
            blow up the response. The export annotates ``notes`` when the
            cap is hit.
    """
    notes: list[str] = []

    transactions = await _safe_select(
        session,
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(Transaction.id.asc()),
        notes=notes,
        note_tag="transactions",
    )

    subscriptions = await _safe_select(
        session,
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.id.asc()),
        notes=notes,
        note_tag="subscriptions",
    )

    chat_threads = await _safe_select(
        session,
        select(ChatThread)
        .where(ChatThread.user_id == user.id)
        .order_by(ChatThread.id.asc()),
        notes=notes,
        note_tag="chat_threads",
    )

    chat_messages = await _safe_select(
        session,
        select(ChatMessage)
        .join(ChatThread, ChatMessage.thread_id == ChatThread.id)
        .where(ChatThread.user_id == user.id)
        .order_by(ChatMessage.id.asc())
        .limit(max_chat_messages + 1),
        notes=notes,
        note_tag="chat_messages",
    )
    truncated = len(chat_messages) > max_chat_messages
    if truncated:
        chat_messages = chat_messages[:max_chat_messages]
        notes.append(
            "chat_messages: truncated at "
            f"{max_chat_messages} rows — contact privacy@labtgbot.example for a "
            "full dump."
        )

    daily_bonus_claims = await _safe_select(
        session,
        select(DailyBonusClaim)
        .where(DailyBonusClaim.user_id == user.id)
        .order_by(DailyBonusClaim.id.asc()),
        notes=notes,
        note_tag="daily_bonus_claims",
    )

    referrals_count = 0
    try:
        referrals_count = int(
            await session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.referred_by == user.id)
            )
            or 0
        )
    except SQLAlchemyError as exc:
        logger.warning("data_export.referrals_failed", error=str(exc))
        notes.append(f"referrals_summary: unavailable ({type(exc).__name__})")

    return UserDataExport(
        schema_version=EXPORT_SCHEMA_VERSION,
        generated_at=datetime.now(UTC),
        user=_user_to_dict(user),
        transactions=[_transaction_to_dict(r) for r in transactions],
        subscriptions=[_subscription_to_dict(r) for r in subscriptions],
        chat_threads=[_chat_thread_to_dict(r) for r in chat_threads],
        chat_messages=[_chat_message_to_dict(r) for r in chat_messages],
        daily_bonus_claims=[_daily_bonus_claim_to_dict(r) for r in daily_bonus_claims],
        referrals_summary={"count": referrals_count},
        notes=notes,
    )
