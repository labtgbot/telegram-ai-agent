"""GDPR Art. 17 — right-to-be-forgotten request handling.

Hard-deleting users is not an option for two reasons:

1. ``transactions.user_id`` has ``ondelete=RESTRICT`` because we have a
   legal accounting obligation to retain transactions for 6 years.
2. Other rows reference the user through foreign keys with mixed
   semantics (chat history, daily-bonus claims, subscriptions). Cascading
   them all atomically is brittle.

Instead, the flow is:

* :func:`request_account_deletion` creates an
  ``account_deletion_requests`` row scheduled 30 days in the future. The
  user can call :func:`cancel_account_deletion` within that window.
* :func:`anonymise_user` (driven by
  :mod:`app.workers.account_deletion`) clears PII fields on
  ``users`` and removes derivative content (chat history, daily-bonus
  cache). It runs idempotently — re-running on an already anonymised
  user is a no-op.

All operations are intended to be called inside a caller-managed
``AsyncSession`` so the API layer controls commit boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.account_deletion import (
    DELETION_STATUS_CANCELLED,
    DELETION_STATUS_COMPLETED,
    DELETION_STATUS_FAILED,
    DELETION_STATUS_PENDING,
    AccountDeletionRequest,
)
from app.models.chat_history import ChatMessage, ChatThread
from app.models.daily_bonus_claim import DailyBonusClaim
from app.models.user import User

logger = get_logger(__name__)

#: Default grace period before anonymisation runs. Mirrors the value
#: documented in :doc:`docs/legal/PRIVACY_POLICY.md` §7.
DEFAULT_GRACE_PERIOD_DAYS = 30

ANONYMISED_USERNAME_PREFIX = "deleted_user_"


class AccountDeletionError(Exception):
    """Base class for account-deletion errors."""


class DeletionAlreadyPendingError(AccountDeletionError):
    """A pending request already exists for the user."""

    def __init__(self, request: AccountDeletionRequest) -> None:
        super().__init__("deletion_already_pending")
        self.request = request


class NoPendingDeletionError(AccountDeletionError):
    """Nothing to cancel — the user has no active request."""


@dataclass(frozen=True)
class DeletionRequestResult:
    """Returned by :func:`request_account_deletion`."""

    request_id: int
    status: str
    scheduled_for: datetime
    requested_at: datetime


@dataclass(frozen=True)
class DeletionStatusSnapshot:
    """Read-side snapshot for the API."""

    pending: bool
    request_id: int | None
    scheduled_for: datetime | None
    requested_at: datetime | None


async def get_pending_deletion(
    session: AsyncSession, user_id: int
) -> AccountDeletionRequest | None:
    """Return the user's active deletion request, if any."""
    stmt = (
        select(AccountDeletionRequest)
        .where(
            AccountDeletionRequest.user_id == user_id,
            AccountDeletionRequest.status == DELETION_STATUS_PENDING,
        )
        .order_by(AccountDeletionRequest.id.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


async def get_deletion_status(
    session: AsyncSession, user_id: int
) -> DeletionStatusSnapshot:
    pending = await get_pending_deletion(session, user_id)
    if pending is None:
        return DeletionStatusSnapshot(
            pending=False,
            request_id=None,
            scheduled_for=None,
            requested_at=None,
        )
    return DeletionStatusSnapshot(
        pending=True,
        request_id=pending.id,
        scheduled_for=pending.scheduled_for,
        requested_at=pending.requested_at,
    )


async def request_account_deletion(
    session: AsyncSession,
    *,
    user: User,
    now: datetime | None = None,
    grace_period_days: int = DEFAULT_GRACE_PERIOD_DAYS,
    requested_via: str | None = None,
    reason: str | None = None,
) -> DeletionRequestResult:
    """Create or return the pending deletion request for ``user``.

    Raises :class:`DeletionAlreadyPendingError` if one already exists —
    the caller can decide whether to surface 409 or echo the existing
    schedule.
    """
    existing = await get_pending_deletion(session, user.id)
    if existing is not None:
        raise DeletionAlreadyPendingError(existing)

    now_utc = now or datetime.now(UTC)
    scheduled = now_utc + timedelta(days=grace_period_days)

    record = AccountDeletionRequest(
        user_id=user.id,
        status=DELETION_STATUS_PENDING,
        requested_at=now_utc,
        scheduled_for=scheduled,
        requested_via=requested_via,
        reason=(reason or None),
    )
    session.add(record)
    await session.flush()

    logger.info(
        "account_deletion.requested",
        user_id=user.id,
        request_id=record.id,
        scheduled_for=scheduled.isoformat(),
        requested_via=requested_via,
    )
    return DeletionRequestResult(
        request_id=record.id,
        status=record.status,
        scheduled_for=record.scheduled_for,
        requested_at=record.requested_at,
    )


async def cancel_account_deletion(
    session: AsyncSession,
    *,
    user: User,
    now: datetime | None = None,
) -> DeletionStatusSnapshot:
    """Cancel the user's pending request."""
    existing = await get_pending_deletion(session, user.id)
    if existing is None:
        raise NoPendingDeletionError("no_pending_deletion")

    now_utc = now or datetime.now(UTC)
    existing.status = DELETION_STATUS_CANCELLED
    existing.cancelled_at = now_utc
    await session.flush()

    logger.info(
        "account_deletion.cancelled",
        user_id=user.id,
        request_id=existing.id,
    )
    return DeletionStatusSnapshot(
        pending=False,
        request_id=existing.id,
        scheduled_for=existing.scheduled_for,
        requested_at=existing.requested_at,
    )


async def list_due_deletions(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> list[AccountDeletionRequest]:
    """Return pending requests whose ``scheduled_for`` is in the past."""
    cutoff = now or datetime.now(UTC)
    stmt = (
        select(AccountDeletionRequest)
        .where(
            AccountDeletionRequest.status == DELETION_STATUS_PENDING,
            AccountDeletionRequest.scheduled_for <= cutoff,
        )
        .order_by(AccountDeletionRequest.scheduled_for.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def anonymise_user(
    session: AsyncSession,
    *,
    user_id: int,
    now: datetime | None = None,
) -> bool:
    """Anonymise the user row and delete derivative content.

    Returns ``True`` when something was changed, ``False`` if the user is
    already anonymised (idempotent). Transactions are preserved (legal
    retention) but no longer point at identifying data.
    """
    user = await session.get(User, user_id)
    if user is None:
        logger.warning("account_deletion.user_missing", user_id=user_id)
        return False

    now_utc = now or datetime.now(UTC)
    placeholder = f"{ANONYMISED_USERNAME_PREFIX}{user.id}"

    if user.username == placeholder and user.first_name is None and user.last_name is None:
        logger.info("account_deletion.already_anonymised", user_id=user.id)
        return False

    user.username = placeholder
    user.first_name = None
    user.last_name = None
    user.language_code = None
    user.is_banned = True
    user.ban_reason = "account_deleted"
    user.banned_until = None
    user.totp_secret = None
    user.totp_enabled = False
    user.last_login_at = None
    user.last_active_at = now_utc

    # Drop derived content that the privacy policy promised to remove.
    await session.execute(
        delete(ChatMessage).where(ChatMessage.user_id == user.id)
    )
    await session.execute(delete(ChatThread).where(ChatThread.user_id == user.id))
    await session.execute(
        delete(DailyBonusClaim).where(DailyBonusClaim.user_id == user.id)
    )

    # Detach referrals so the network graph does not leak the (now
    # anonymised) account as a referrer.
    await session.execute(
        update(User).where(User.referred_by == user.id).values(referred_by=None)
    )

    logger.info("account_deletion.anonymised", user_id=user.id)
    return True


async def mark_deletion_completed(
    session: AsyncSession,
    *,
    request: AccountDeletionRequest,
    now: datetime | None = None,
) -> None:
    """Flip the request row to ``completed`` after the worker is done."""
    now_utc = now or datetime.now(UTC)
    request.status = DELETION_STATUS_COMPLETED
    request.completed_at = now_utc
    await session.flush()


async def mark_deletion_failed(
    session: AsyncSession,
    *,
    request_id: int,
    failure_reason: str,
    now: datetime | None = None,
) -> None:
    """Persist a worker failure for a pending deletion request."""
    now_utc = now or datetime.now(UTC)
    await session.execute(
        update(AccountDeletionRequest)
        .where(
            AccountDeletionRequest.id == request_id,
            AccountDeletionRequest.status == DELETION_STATUS_PENDING,
        )
        .values(
            status=DELETION_STATUS_FAILED,
            failed_at=now_utc,
            failure_reason=failure_reason,
        )
        .execution_options(synchronize_session=False)
    )
    await session.flush()
