"""Token Management Service.

Implements atomic credit (``add``), debit (``spend``), administrator
manual bonuses (``manual_bonus``) and refunds (``refund``).  Each public
write method is a transactional unit:

* a row-level lock is taken on the user via ``SELECT ... FOR UPDATE``;
* the balance update and the audit rows (``transactions`` and, for
  spends, ``token_usage_logs``) are flushed to the database inside the
  same transaction;
* the lock is held until the active transaction is committed or rolled
  back by the caller.

This follows the existing unit-of-work pattern in the codebase (see
``app.services.bot_users.register_or_update_user``) — services flush
their work, the request handler commits.  ``InsufficientTokensError``
is raised *before* any state mutation, so the caller may continue using
the session after handling the error.

The ``users.token_balance >= 0`` invariant is enforced here rather than
at the DB level so the API can surface a structured error to the UI —
see ``docs/DATABASE_SCHEMA.md > Invariants``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.metrics import observe_spend
from app.models.token_usage_log import TokenUsageLog
from app.models.transaction import Transaction
from app.models.user import User
from app.services.balance_cache import BalanceCache

logger = get_logger(__name__)


# ----------------------------------------------------------------- exceptions


class TokenServiceError(Exception):
    """Base class for all token-service errors."""


class InvalidAmountError(TokenServiceError):
    """Raised when ``amount`` is not a positive integer."""


class UserNotFoundError(TokenServiceError):
    """Raised when the referenced user does not exist."""


class InsufficientTokensError(TokenServiceError):
    """Raised when a spend would drive the balance below zero.

    Exposes ``required`` and ``available`` so the API layer can pass
    structured data back to the UI.
    """

    def __init__(self, *, required: int, available: int) -> None:
        super().__init__(f"insufficient tokens: required={required}, available={available}")
        self.required = required
        self.available = available


class TransactionNotFoundError(TokenServiceError):
    """Raised when the transaction referenced for a refund is missing."""


class TransactionNotRefundableError(TokenServiceError):
    """Raised when the transaction cannot be refunded.

    Currently this means: it is not of type ``spend`` or ``purchase``,
    or it has already been refunded.
    """


# --------------------------------------------------------------- result types

CREDIT_TYPES: frozenset[str] = frozenset({"bonus", "purchase", "manual_bonus"})
REFUNDABLE_TYPES: frozenset[str] = frozenset({"spend", "purchase"})
_DIRTY_BALANCE_CACHE_USERS_KEY = "token_service.dirty_balance_cache_user_ids"


@dataclass(frozen=True)
class TokenOperationResult:
    user_id: int
    amount: int
    new_balance: int
    transaction_id: int
    transaction_type: str


@dataclass(frozen=True)
class SpendResult(TokenOperationResult):
    usage_log_id: int = 0


@dataclass(frozen=True)
class UsageHistoryPage:
    items: Sequence[TokenUsageLog]
    total: int
    page: int
    limit: int
    has_more: bool = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "has_more", (self.page * self.limit) < self.total)


# ------------------------------------------------------------------- service


def _coerce_amount(amount: int) -> int:
    """Validate ``amount`` is a positive integer and return it."""
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise InvalidAmountError("amount must be an integer")
    if amount <= 0:
        raise InvalidAmountError("amount must be > 0")
    return amount


class TokenService:
    """Service object — instantiate per request with the active session.

    Methods flush their writes to the database but do **not** commit;
    the caller (typically an API endpoint) controls the outer
    transaction.  All write methods take ``SELECT ... FOR UPDATE`` row
    locks so concurrent calls are serialised on the user row.

    Pass a :class:`BalanceCache` to enable the Redis read-through layer
    (issue #36): :meth:`get_balance` will hit Redis first and the write
    methods will invalidate the cached value as they mutate
    ``users.token_balance``.  When ``balance_cache`` is omitted the
    service falls back to the pre-cache behaviour, which keeps tests
    that build a service with only a session working unchanged.
    """

    def __init__(
        self,
        session: AsyncSession,
        balance_cache: BalanceCache | None = None,
    ) -> None:
        self.session = session
        self._balance_cache = balance_cache

    # ------------------------------------------------------------- internal

    def _mark_balance_cache_dirty(self, user_id: int) -> None:
        dirty_user_ids = self.session.info.setdefault(_DIRTY_BALANCE_CACHE_USERS_KEY, set())
        dirty_user_ids.add(int(user_id))

    def _is_balance_cache_dirty(self, user_id: int) -> bool:
        dirty_user_ids = self.session.info.get(_DIRTY_BALANCE_CACHE_USERS_KEY)
        return isinstance(dirty_user_ids, set) and int(user_id) in dirty_user_ids

    async def _lock_user(self, user_id: int) -> User:
        """Take a row-level lock on the user and return the ORM object.

        On PostgreSQL ``SELECT ... FOR UPDATE`` blocks concurrent writers
        until the surrounding transaction commits / rolls back, which is
        what guarantees the balance invariant under contention.
        """
        stmt = select(User).where(User.id == user_id).with_for_update()
        result = await self.session.execute(stmt)
        user = result.scalar_one_or_none()
        if user is None:
            raise UserNotFoundError(f"user {user_id} not found")
        return user

    # ------------------------------------------------------------- queries

    async def get_balance(self, user_id: int) -> int:
        """Return the current token balance (no lock taken).

        Reads go through the optional :class:`BalanceCache` first; on a
        miss we fetch from the DB and write the value back so the next
        request can serve from Redis. After this session mutates a
        user's balance, reads for that user bypass Redis and do not
        hydrate it, so uncommitted in-transaction values are never
        published by this service.
        """
        cache_dirty = self._is_balance_cache_dirty(user_id)
        if self._balance_cache is not None and not cache_dirty:
            cached = await self._balance_cache.get(user_id)
            if cached is not None:
                return cached

        stmt = select(User.token_balance).where(User.id == user_id)
        result = await self.session.execute(stmt)
        balance = result.scalar_one_or_none()
        if balance is None:
            raise UserNotFoundError(f"user {user_id} not found")
        balance_int = int(balance)
        if self._balance_cache is not None and not cache_dirty:
            await self._balance_cache.set(user_id, balance_int)
        return balance_int

    async def usage_history(
        self,
        user_id: int,
        *,
        page: int = 1,
        limit: int = 20,
    ) -> UsageHistoryPage:
        """Return a paginated slice of the user's token-usage history.

        ``page`` is 1-indexed.  Values out of safe ranges are clamped so
        the endpoint cannot crash on user input.
        """
        page = max(int(page or 1), 1)
        limit = max(min(int(limit or 20), 100), 1)
        offset = (page - 1) * limit

        await self._assert_user_exists(user_id)

        total_stmt = (
            select(func.count()).select_from(TokenUsageLog).where(TokenUsageLog.user_id == user_id)
        )
        total = int((await self.session.execute(total_stmt)).scalar_one())

        items_stmt = (
            select(TokenUsageLog)
            .where(TokenUsageLog.user_id == user_id)
            .order_by(TokenUsageLog.created_at.desc(), TokenUsageLog.id.desc())
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.session.execute(items_stmt)).scalars().all()
        return UsageHistoryPage(items=list(rows), total=total, page=page, limit=limit)

    async def _assert_user_exists(self, user_id: int) -> None:
        stmt = select(User.id).where(User.id == user_id)
        if (await self.session.execute(stmt)).scalar_one_or_none() is None:
            raise UserNotFoundError(f"user {user_id} not found")

    async def _invalidate_balance_cache(self, user_id: int) -> None:
        """Drop cached balance after an in-transaction mutation.

        Write methods flush but do not commit, so Redis must not receive
        the new balance here: an outer rollback would leave an
        uncommitted value cached until TTL. Deleting the key keeps the
        cache read-through only; the next balance read hydrates Redis
        from the committed DB value.
        """
        self._mark_balance_cache_dirty(user_id)
        if self._balance_cache is None:
            return
        try:
            await self._balance_cache.invalidate(user_id)
        except Exception as exc:  # noqa: BLE001 — caching is best-effort
            logger.warning(
                "balance_cache.invalidate_failed",
                user_id=user_id,
                error=str(exc),
            )

    async def _refresh_cache(self, user_id: int, new_balance: int) -> None:
        """Backward-compatible private hook; now invalidates instead of writing."""
        await self._invalidate_balance_cache(user_id)

    # ----------------------------------------------------------------- add

    async def add(
        self,
        *,
        user_id: int,
        amount: int,
        transaction_type: str = "bonus",
        package_name: str | None = None,
        payment_id: str | None = None,
        payment_method: str | None = None,
        payment_status: str | None = "completed",
        stars_amount: int | None = None,
        usd_amount: Decimal | float | None = None,
        discount_percent: int | None = None,
        meta: dict[str, Any] | None = None,
    ) -> TokenOperationResult:
        """Credit ``amount`` tokens to ``user_id`` atomically.

        ``transaction_type`` must be one of ``bonus``, ``purchase`` or
        ``manual_bonus``.  ``purchase`` additionally bumps
        ``users.total_tokens_purchased``.

        ``meta`` is reserved for forward-compatibility — it is currently
        ignored on the DB side, but logged for traceability.
        """
        amount = _coerce_amount(amount)
        if transaction_type not in CREDIT_TYPES:
            raise InvalidAmountError(
                f"transaction_type {transaction_type!r} is not a credit type; "
                f"expected one of {sorted(CREDIT_TYPES)}"
            )

        user = await self._lock_user(user_id)
        user.token_balance = int(user.token_balance or 0) + amount
        if transaction_type == "purchase":
            user.total_tokens_purchased = int(user.total_tokens_purchased or 0) + amount

        usd_value = Decimal(str(usd_amount)) if usd_amount is not None else None
        now = datetime.now(UTC)
        tx = Transaction(
            user_id=user.id,
            transaction_type=transaction_type,
            tokens_amount=amount,
            stars_amount=stars_amount,
            usd_amount=usd_value,
            package_name=package_name,
            discount_percent=discount_percent,
            payment_id=payment_id,
            payment_status=payment_status,
            payment_method=payment_method,
            completed_at=now if payment_status == "completed" else None,
        )
        self.session.add(tx)
        await self.session.flush()

        await self._invalidate_balance_cache(user.id)

        logger.info(
            "tokens.add",
            user_id=user.id,
            amount=amount,
            transaction_type=transaction_type,
            transaction_id=tx.id,
            new_balance=user.token_balance,
            meta=meta or None,
        )
        return TokenOperationResult(
            user_id=user.id,
            amount=amount,
            new_balance=int(user.token_balance),
            transaction_id=int(tx.id),
            transaction_type=transaction_type,
        )

    # --------------------------------------------------------------- spend

    async def spend(
        self,
        *,
        user_id: int,
        amount: int,
        service: str,
        request_params: dict[str, Any] | None = None,
        response_status: str | None = "ok",
        processing_time_ms: int | None = None,
        composio_tool: str | None = None,
        mcp_server: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> SpendResult:
        """Atomically debit ``amount`` tokens for ``service``.

        Raises :class:`InsufficientTokensError` *before* any state is
        modified when the user balance would drop below zero.
        """
        amount = _coerce_amount(amount)
        if not service or not str(service).strip():
            raise InvalidAmountError("service is required")
        service = str(service).strip()[:100]

        user = await self._lock_user(user_id)
        current = int(user.token_balance or 0)
        if current < amount:
            raise InsufficientTokensError(required=amount, available=current)

        user.token_balance = current - amount
        user.total_tokens_spent = int(user.total_tokens_spent or 0) + amount
        user.total_requests = int(user.total_requests or 0) + 1

        now = datetime.now(UTC)
        tx = Transaction(
            user_id=user.id,
            transaction_type="spend",
            tokens_amount=amount,
            package_name=service,
            payment_status="completed",
            completed_at=now,
        )
        self.session.add(tx)

        usage = TokenUsageLog(
            user_id=user.id,
            service_type=service,
            tokens_consumed=amount,
            request_params=request_params,
            response_status=response_status,
            processing_time_ms=processing_time_ms,
            composio_tool=composio_tool[:255] if composio_tool is not None else None,
            mcp_server=mcp_server[:255] if mcp_server is not None else None,
        )
        self.session.add(usage)
        await self.session.flush()

        await self._invalidate_balance_cache(user.id)

        logger.info(
            "tokens.spend",
            user_id=user.id,
            amount=amount,
            service=service,
            transaction_id=tx.id,
            usage_log_id=usage.id,
            new_balance=user.token_balance,
            meta=meta or None,
        )
        observe_spend(service=service, tokens=amount)
        return SpendResult(
            user_id=user.id,
            amount=amount,
            new_balance=int(user.token_balance),
            transaction_id=int(tx.id),
            transaction_type="spend",
            usage_log_id=int(usage.id),
        )

    async def record_spend_result(
        self,
        *,
        usage_log_id: int,
        response_status: str | None,
        processing_time_ms: int | None = None,
        composio_tool: str | None = None,
        mcp_server: str | None = None,
        request_params: dict[str, Any] | None = None,
    ) -> None:
        """Attach provider outcome metadata to an existing spend usage row.

        Debit-first services reserve tokens before the provider call.  Once
        the provider returns, they use this hook to replace the provisional
        usage-log status with the actual provider metadata.
        """
        stmt = select(TokenUsageLog).where(TokenUsageLog.id == int(usage_log_id))
        usage = (await self.session.execute(stmt)).scalar_one_or_none()
        if usage is None:
            logger.warning(
                "tokens.spend_usage_log_missing",
                usage_log_id=usage_log_id,
                response_status=response_status,
            )
            return

        usage.response_status = response_status
        usage.processing_time_ms = processing_time_ms
        usage.composio_tool = composio_tool[:255] if composio_tool else None
        usage.mcp_server = mcp_server[:255] if mcp_server else None
        if request_params is not None:
            usage.request_params = request_params
        await self.session.flush()

        logger.debug(
            "tokens.spend_usage_log_updated",
            usage_log_id=usage_log_id,
            response_status=response_status,
            composio_tool=usage.composio_tool,
            mcp_server=usage.mcp_server,
        )

    # -------------------------------------------------------- manual_bonus

    async def manual_bonus(
        self,
        *,
        user_id: int,
        amount: int,
        reason: str,
        admin_id: int | None = None,
    ) -> TokenOperationResult:
        """Credit ``amount`` tokens as an admin-initiated manual bonus.

        ``reason`` is stored in ``Transaction.package_name`` so the row
        carries an audit-friendly tag (no free-form column exists in
        Phase 1 schema).  ``admin_id`` is recorded in logs only.
        """
        if not reason or not reason.strip():
            raise InvalidAmountError("reason is required for manual bonus")
        reason = reason.strip()[:100]

        result = await self.add(
            user_id=user_id,
            amount=amount,
            transaction_type="manual_bonus",
            package_name=reason,
            payment_status="completed",
            meta={"admin_id": admin_id, "reason": reason},
        )
        logger.info(
            "tokens.manual_bonus",
            user_id=user_id,
            amount=amount,
            admin_id=admin_id,
            reason=reason,
            transaction_id=result.transaction_id,
        )
        return result

    # -------------------------------------------------------------- refund

    async def refund(
        self,
        *,
        transaction_id: int,
        reason: str | None = None,
    ) -> TokenOperationResult:
        """Reverse a previous ``spend`` or ``purchase`` transaction.

        Creates a new ``refund`` transaction that reverses the original:

        * refund of ``spend`` — re-credits the tokens to the user and
          rolls back ``users.total_tokens_spent``;
        * refund of ``purchase`` — debits the tokens (user got money
          back externally) and rolls back ``users.total_tokens_purchased``.

        Already-refunded transactions cannot be refunded a second time.
        """
        stmt = select(Transaction).where(Transaction.id == transaction_id).with_for_update()
        original = (await self.session.execute(stmt)).scalar_one_or_none()
        if original is None:
            raise TransactionNotFoundError(f"transaction {transaction_id} not found")
        if original.transaction_type not in REFUNDABLE_TYPES:
            raise TransactionNotRefundableError(
                f"transaction {transaction_id} type "
                f"{original.transaction_type!r} is not refundable"
            )

        # Embed the original type in the marker so the reconcile query can
        # classify refund rows without re-joining to the source transaction.
        payment_marker = f"refund:{original.transaction_type}:tx={transaction_id}"
        existing = await self.session.execute(
            select(Transaction.id).where(
                Transaction.transaction_type == "refund",
                Transaction.payment_id == payment_marker,
            )
        )
        if existing.scalar_one_or_none() is not None:
            raise TransactionNotRefundableError(f"transaction {transaction_id} already refunded")

        user = await self._lock_user(original.user_id)
        amount = int(original.tokens_amount)
        if original.transaction_type == "spend":
            user.token_balance = int(user.token_balance or 0) + amount
            user.total_tokens_spent = max(int(user.total_tokens_spent or 0) - amount, 0)
        else:  # purchase
            user.token_balance = max(int(user.token_balance or 0) - amount, 0)
            user.total_tokens_purchased = max(int(user.total_tokens_purchased or 0) - amount, 0)

        now = datetime.now(UTC)
        tx = Transaction(
            user_id=user.id,
            transaction_type="refund",
            tokens_amount=amount,
            package_name=(reason or "refund")[:100],
            payment_id=payment_marker,
            payment_status="completed",
            completed_at=now,
        )
        self.session.add(tx)
        await self.session.flush()

        await self._invalidate_balance_cache(user.id)

        logger.info(
            "tokens.refund",
            user_id=user.id,
            amount=amount,
            original_transaction_id=transaction_id,
            refund_transaction_id=tx.id,
            new_balance=user.token_balance,
            reason=reason,
        )
        return TokenOperationResult(
            user_id=user.id,
            amount=amount,
            new_balance=int(user.token_balance),
            transaction_id=int(tx.id),
            transaction_type="refund",
        )


# ------------------------------------------------------------------- audit


@dataclass(frozen=True)
class BalanceAudit:
    user_id: int
    stored_balance: int
    computed_balance: int
    drift: int

    @property
    def is_consistent(self) -> bool:
        return self.drift == 0


async def reconcile_user_balance(session: AsyncSession, user_id: int) -> BalanceAudit:
    """Recompute the balance from the transaction ledger and compare.

    The expected balance is::

        SUM(credits) - SUM(debits)

    where credits = ``purchase + bonus + manual_bonus + refund-of-spend``
    and debits = ``spend + refund-of-purchase``.  Refund rows are
    classified via their ``payment_id`` marker
    (``refund:{original_type}:tx=...``).

    Any non-zero ``drift`` indicates the materialised
    ``users.token_balance`` and the ledger have diverged — this should
    never happen but the daily reconcile job alerts on it.
    """
    stored_stmt = select(User.token_balance).where(User.id == user_id)
    stored = (await session.execute(stored_stmt)).scalar_one_or_none()
    if stored is None:
        raise UserNotFoundError(f"user {user_id} not found")

    base_credit_stmt = (
        select(func.coalesce(func.sum(Transaction.tokens_amount), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.transaction_type.in_(("purchase", "bonus", "manual_bonus")))
    )
    spend_stmt = (
        select(func.coalesce(func.sum(Transaction.tokens_amount), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.transaction_type == "spend")
    )
    refund_credit_stmt = (
        select(func.coalesce(func.sum(Transaction.tokens_amount), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.transaction_type == "refund")
        .where(Transaction.payment_id.like("refund:spend:%"))
    )
    refund_debit_stmt = (
        select(func.coalesce(func.sum(Transaction.tokens_amount), 0))
        .where(Transaction.user_id == user_id)
        .where(Transaction.transaction_type == "refund")
        .where(Transaction.payment_id.like("refund:purchase:%"))
    )
    base_credit = int((await session.execute(base_credit_stmt)).scalar_one())
    spend = int((await session.execute(spend_stmt)).scalar_one())
    refund_credit = int((await session.execute(refund_credit_stmt)).scalar_one())
    refund_debit = int((await session.execute(refund_debit_stmt)).scalar_one())
    computed = base_credit + refund_credit - spend - refund_debit
    return BalanceAudit(
        user_id=user_id,
        stored_balance=int(stored),
        computed_balance=computed,
        drift=int(stored) - computed,
    )


async def reconcile_all_balances(
    session: AsyncSession, *, limit: int | None = None
) -> list[BalanceAudit]:
    """Audit every user's balance against the ledger.

    Intended to be called by a daily reconcile worker (see Celery beat
    in ``docs/ARCHITECTURE.md``).  Returns the full list of
    :class:`BalanceAudit` rows; callers typically filter by
    ``not row.is_consistent`` to emit alerts.
    """
    stmt = select(User.id)
    if limit is not None:
        stmt = stmt.limit(int(limit))
    ids = list((await session.execute(stmt)).scalars().all())
    return [await reconcile_user_balance(session, int(uid)) for uid in ids]


__all__ = [
    "BalanceAudit",
    "CREDIT_TYPES",
    "InsufficientTokensError",
    "InvalidAmountError",
    "REFUNDABLE_TYPES",
    "SpendResult",
    "TokenOperationResult",
    "TokenService",
    "TokenServiceError",
    "TransactionNotFoundError",
    "TransactionNotRefundableError",
    "UsageHistoryPage",
    "UserNotFoundError",
    "reconcile_all_balances",
    "reconcile_user_balance",
]
