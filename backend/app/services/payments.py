"""Telegram Stars payment service.

Phase 2 of the project introduces paid token packages purchased via the
Telegram Stars currency (``XTR``).  The flow we implement is:

1. The Mini App (or bot) calls :meth:`PaymentService.create_invoice` with
   a package code and the authenticated user.  We persist a pending
   :class:`~app.models.transaction.Transaction` row tagged
   ``payment_id="invoice:<payload>"`` and ask the Bot API for an
   ``invoice_link`` that the client can open.
2. Telegram delivers a ``pre_checkout_query`` update.
   :meth:`PaymentService.confirm_pre_checkout` validates that the payload
   matches a pending invoice (or is a known subscription renewal) and
   answers Telegram so the payment can complete.
3. Telegram delivers a ``successful_payment`` message.
   :meth:`PaymentService.finalize_successful_payment` is **idempotent**
   on the ``telegram_payment_charge_id``: a duplicate webhook returns
   the original :class:`PaymentResult` without crediting tokens twice.

Idempotency strategy
~~~~~~~~~~~~~~~~~~~~

We never rely on Telegram-side deduplication.  Two columns of the
``transactions`` table are used as idempotency keys:

* the *pending* row is stored with ``payment_id="invoice:<payload>"`` so
  ``pre_checkout`` can find it again;
* on success the same row is upgraded to
  ``payment_id="tg:<charge_id>"`` + ``payment_status="completed"``.

Before doing any state mutation, the finaliser checks whether a row with
``payment_id="tg:<charge_id>"`` already exists.  If so it short-circuits
and returns the previously stored result — that is how we satisfy the
"duplicate webhook MUST NOT double-credit" acceptance criterion.

A partial unique index on ``transactions.payment_id`` (migration
``0003_payment_idempotency``) hardens this at the database level so that
two simultaneous webhook deliveries can never both insert.

Subscriptions
~~~~~~~~~~~~~

The Pro plan is a recurring monthly bundle.  The first successful
payment creates (or extends) a :class:`~app.models.subscription.Subscription`
row whose ``expires_at`` is now+30d.  A background task —
:func:`process_subscription_renewals` — runs daily, scans rows whose
``expires_at`` is in the past (and ``auto_renew=True``), credits the
next month's tokens via :class:`~app.services.token_service.TokenService.add`
and pushes ``expires_at`` forward by another 30 days.  Telegram Stars
subscriptions also send their own renewal webhooks; those are handled
through the same ``finalize_successful_payment`` codepath because the
``telegram_payment_charge_id`` differs from the original purchase.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.client import TelegramApiError, TelegramClient
from app.core.logging import get_logger
from app.core.metrics import observe_payment_event, observe_purchase
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.models.user import User
from app.services.payment_packages import (
    PRO_SUBSCRIPTION_DAYS,
    PaymentPackage,
    get_package,
)
from app.services.pricing import (
    apply_pricing_to_package,
    load_pricing_config,
)
from app.services.token_service import TokenService, UserNotFoundError

logger = get_logger(__name__)

INVOICE_PREFIX = "invoice:"
CHARGE_PREFIX = "tg:"
REFERRAL_BONUS_PREFIX = "referral:"
REFERRAL_BONUS_PACKAGE = "referral_bonus"
DEFAULT_REFERRAL_BONUS_TOKENS = 100
DEFAULT_CURRENCY = "XTR"
PAYMENT_METHOD = "telegram_stars"


# ----------------------------------------------------------------- exceptions


class PaymentError(Exception):
    """Base class for payment service errors."""


class PackageNotFoundError(PaymentError):
    """Raised when the requested package code is unknown."""


class InvoiceNotFoundError(PaymentError):
    """Raised when no pending invoice exists for the given payload."""


class InvoicePayloadInvalidError(PaymentError):
    """Raised when the payload format is malformed."""


class PaymentAlreadyProcessedError(PaymentError):
    """Raised when finalisation would double-credit (kept for diagnostics).

    The public ``finalize_successful_payment`` method swallows this and
    returns the existing :class:`PaymentResult` instead, but the error
    is exported so tests can opt in to the strict variant.
    """


# --------------------------------------------------------------- result types


@dataclass(frozen=True)
class InvoiceCreation:
    """Outcome of :meth:`PaymentService.create_invoice`."""

    invoice_id: str
    payload: str
    package_code: str
    stars_amount: int
    tokens_amount: int
    telegram_invoice_link: str
    transaction_id: int
    is_subscription: bool


@dataclass(frozen=True)
class PaymentResult:
    """Outcome of finalising a successful payment."""

    transaction_id: int
    user_id: int
    tokens_credited: int
    stars_amount: int
    package_code: str
    new_balance: int
    is_subscription: bool
    subscription_id: int | None = None
    expires_at: datetime | None = None
    already_processed: bool = False


@dataclass(frozen=True)
class PaymentStatus:
    """Snapshot used by ``GET /api/v1/payment/status/{invoice_id}``."""

    invoice_id: str
    status: str
    package_code: str | None
    tokens_credited: int
    stars_amount: int | None
    transaction_id: int
    created_at: datetime
    completed_at: datetime | None
    telegram_payment_charge_id: str | None


# --------------------------------------------------------- payload generation


def _generate_payload(package_code: str, user_id: int) -> str:
    """Build a unique-but-traceable invoice payload.

    Telegram echoes this string back in ``pre_checkout_query.invoice_payload``
    and ``successful_payment.invoice_payload``.  The package + user prefix
    makes log lines self-describing; the random suffix prevents collisions
    when the same user creates multiple invoices for the same package.
    """
    nonce = secrets.token_urlsafe(12)
    return f"pkg={package_code};u={user_id};n={nonce}"


def parse_payload(payload: str) -> dict[str, str]:
    """Parse a payload produced by :func:`_generate_payload`.

    Returns a flat dict of fields.  Raises :class:`InvoicePayloadInvalidError`
    if the payload is malformed.
    """
    if not payload or not isinstance(payload, str):
        raise InvoicePayloadInvalidError("payload is empty")
    out: dict[str, str] = {}
    for part in payload.split(";"):
        if not part:
            continue
        key, sep, value = part.partition("=")
        if not sep:
            raise InvoicePayloadInvalidError(f"malformed payload part: {part!r}")
        out[key.strip()] = value.strip()
    if "pkg" not in out or "u" not in out:
        raise InvoicePayloadInvalidError("payload missing pkg/u fields")
    return out


# ------------------------------------------------------------------- service


class PaymentService:
    """Service object — instantiate per request with the active session.

    Mirrors :class:`~app.services.token_service.TokenService` conventions:
    write methods flush but do **not** commit; the API endpoint or webhook
    handler controls the outer transaction.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        client: TelegramClient | None = None,
    ) -> None:
        self.session = session
        self._client = client

    @property
    def client(self) -> TelegramClient:
        if self._client is None:
            raise RuntimeError("PaymentService requires a TelegramClient for this call")
        return self._client

    # --------------------------------------------------------- create_invoice

    async def create_invoice(
        self,
        *,
        user_id: int,
        package_code: str,
    ) -> InvoiceCreation:
        """Generate a Telegram invoice link for ``package_code``.

        Persists a pending ``Transaction`` row tagged with the payload so
        the pre-checkout and successful-payment webhooks can correlate the
        purchase back to the user.
        """
        base_package = get_package(package_code)
        if base_package is None:
            raise PackageNotFoundError(f"unknown package: {package_code!r}")

        # Apply admin overrides → the pending row stores the *effective*
        # price the user agreed to, so a later admin tweak does not
        # invalidate an in-flight invoice.
        pricing_config = await load_pricing_config(self.session)
        package = apply_pricing_to_package(base_package, pricing_config)

        user = await self._get_user(user_id)
        payload = _generate_payload(package.code, user.id)

        pending = Transaction(
            user_id=user.id,
            transaction_type="purchase",
            tokens_amount=package.tokens,
            stars_amount=package.stars,
            package_name=package.code,
            payment_id=f"{INVOICE_PREFIX}{payload}",
            payment_status="pending",
            payment_method=PAYMENT_METHOD,
        )
        self.session.add(pending)
        await self.session.flush()

        try:
            invoice_link = await self.client.create_invoice_link(
                title=package.title,
                description=package.description,
                payload=payload,
                currency=DEFAULT_CURRENCY,
                prices=[{"label": package.title, "amount": package.stars}],
                subscription_period=(
                    package.subscription_days * 24 * 3600
                    if package.is_subscription
                    else None
                ),
            )
        except TelegramApiError:
            # Roll the pending row back so retries don't accumulate
            # garbage.  The outer transaction is left in a usable state
            # for the endpoint to surface the failure.
            await self.session.delete(pending)
            await self.session.flush()
            raise

        logger.info(
            "payment.invoice_created",
            user_id=user.id,
            package=package.code,
            payload=payload,
            transaction_id=pending.id,
            stars=package.stars,
        )
        observe_payment_event(event="invoice_created", package=package.code)
        return InvoiceCreation(
            invoice_id=payload,
            payload=payload,
            package_code=package.code,
            stars_amount=package.stars,
            tokens_amount=package.tokens,
            telegram_invoice_link=invoice_link,
            transaction_id=int(pending.id),
            is_subscription=package.is_subscription,
        )

    # ----------------------------------------------------- confirm_pre_checkout

    async def confirm_pre_checkout(
        self,
        *,
        payload: str,
        total_amount: int,
        currency: str,
    ) -> PaymentPackage:
        """Validate a ``pre_checkout_query`` and return the matched package.

        Telegram requires the bot to answer within 10 seconds — callers
        should reply immediately after this returns.  Raises
        :class:`InvoicePayloadInvalidError` (or :class:`PackageNotFoundError`
        / :class:`InvoiceNotFoundError`) so the dispatcher can answer
        ``ok=False`` with an explanation.
        """
        if currency.upper() != DEFAULT_CURRENCY:
            raise InvoicePayloadInvalidError(
                f"unsupported currency: {currency!r}"
            )
        parts = parse_payload(payload)
        package = get_package(parts.get("pkg"))
        if package is None:
            raise PackageNotFoundError(
                f"pre_checkout: unknown package in payload {payload!r}"
            )

        pending = await self._find_pending_invoice(payload)
        # Validate against the price the user actually agreed to:
        # the pending invoice holds the effective (admin-overridden) price.
        # Subscription renewals have no pending row → fall back to the
        # locked static price, which is exactly what Telegram bills.
        expected_stars = (
            int(pending.stars_amount or 0)
            if pending is not None and pending.stars_amount is not None
            else int(package.stars)
        )
        if int(total_amount) != expected_stars:
            raise InvoicePayloadInvalidError(
                f"pre_checkout: stars mismatch "
                f"(expected={expected_stars}, telegram={total_amount})"
            )

        if pending is None and not package.is_subscription:
            # Subscriptions can renew without a pending invoice (Telegram
            # bills automatically) — those flow straight to the success
            # webhook.  One-time purchases must always have a pending row.
            raise InvoiceNotFoundError(
                f"no pending invoice for payload {payload!r}"
            )
        return package

    # ----------------------------------------------- finalize_successful_payment

    async def finalize_successful_payment(
        self,
        *,
        telegram_user_id: int,
        payload: str,
        total_amount: int,
        currency: str,
        telegram_payment_charge_id: str,
        provider_payment_charge_id: str | None = None,
        is_recurring: bool = False,
    ) -> PaymentResult:
        """Credit tokens for a ``successful_payment`` update — idempotent.

        Duplicate deliveries (same ``telegram_payment_charge_id``) return
        the previously stored result without touching the balance.
        """
        if currency.upper() != DEFAULT_CURRENCY:
            raise InvoicePayloadInvalidError(
                f"unsupported currency: {currency!r}"
            )

        existing = await self._find_completed_by_charge_id(telegram_payment_charge_id)
        if existing is not None:
            user = await self._get_user(existing.user_id)
            logger.info(
                "payment.duplicate_webhook",
                user_id=user.id,
                charge_id=telegram_payment_charge_id,
                transaction_id=existing.id,
            )
            observe_payment_event(
                event="duplicate", package=existing.package_name
            )
            return PaymentResult(
                transaction_id=int(existing.id),
                user_id=int(user.id),
                tokens_credited=int(existing.tokens_amount),
                stars_amount=int(existing.stars_amount or 0),
                package_code=str(existing.package_name or ""),
                new_balance=int(user.token_balance or 0),
                is_subscription=is_recurring,
                already_processed=True,
            )

        parts = parse_payload(payload)
        package = get_package(parts.get("pkg"))
        if package is None:
            raise PackageNotFoundError(
                f"successful_payment: unknown package in payload {payload!r}"
            )

        try:
            user_id = int(parts["u"])
        except (KeyError, ValueError) as exc:
            raise InvoicePayloadInvalidError("payload user id invalid") from exc

        token_service = TokenService(self.session)
        charge_marker = f"{CHARGE_PREFIX}{telegram_payment_charge_id}"

        pending = await self._find_pending_invoice(payload)
        # Validate the inbound amount against the pending row (which
        # captured the admin-overridden price at invoice time), or the
        # static package price for subscription renewals.
        expected_stars = (
            int(pending.stars_amount or 0)
            if pending is not None and pending.stars_amount is not None
            else int(package.stars)
        )
        if int(total_amount) != expected_stars:
            raise InvoicePayloadInvalidError(
                f"successful_payment: stars mismatch "
                f"(expected={expected_stars}, telegram={total_amount})"
            )

        if pending is not None and not is_recurring:
            # Upgrade the existing pending row in place — credit the
            # tokens that were actually quoted in the invoice, not the
            # current static catalogue value.
            effective_tokens = int(pending.tokens_amount or package.tokens)
            user = await token_service._lock_user(pending.user_id)
            user.token_balance = int(user.token_balance or 0) + effective_tokens
            user.total_tokens_purchased = (
                int(user.total_tokens_purchased or 0) + effective_tokens
            )
            pending.payment_id = charge_marker
            pending.payment_status = "completed"
            pending.completed_at = datetime.now(UTC)
            try:
                await self.session.flush()
            except IntegrityError:
                # Lost the race to another worker — re-fetch and return.
                await self.session.rollback()
                existing = await self._find_completed_by_charge_id(
                    telegram_payment_charge_id
                )
                if existing is None:
                    raise
                user2 = await self._get_user(existing.user_id)
                return PaymentResult(
                    transaction_id=int(existing.id),
                    user_id=int(user2.id),
                    tokens_credited=int(existing.tokens_amount),
                    stars_amount=int(existing.stars_amount or 0),
                    package_code=str(existing.package_name or ""),
                    new_balance=int(user2.token_balance or 0),
                    is_subscription=is_recurring,
                    already_processed=True,
                )
            tx = pending
        else:
            # No pending row (subscription renewal, or pending was
            # already cleaned up) — credit via TokenService.add which
            # creates a fresh purchase row.
            result = await token_service.add(
                user_id=user_id,
                amount=package.tokens,
                transaction_type="purchase",
                package_name=package.code,
                payment_id=charge_marker,
                payment_method=PAYMENT_METHOD,
                payment_status="completed",
                stars_amount=package.stars,
                meta={
                    "charge_id": telegram_payment_charge_id,
                    "provider_charge_id": provider_payment_charge_id,
                    "recurring": is_recurring,
                },
            )
            tx = await self._fetch_transaction(result.transaction_id)
            user = await self._get_user(user_id)

        await self._maybe_credit_referral_bonus(
            referee=user,
            purchase_transaction_id=int(tx.id),
        )

        subscription_id: int | None = None
        expires_at: datetime | None = None
        if package.is_subscription:
            sub = await self._upsert_subscription(
                user_id=user.id,
                package=package,
                transaction_id=int(tx.id),
            )
            subscription_id = int(sub.id) if sub.id else None
            expires_at = sub.expires_at
            if not user.is_premium:
                user.is_premium = True
            if expires_at is not None and (
                user.premium_expires_at is None
                or user.premium_expires_at < expires_at
            ):
                user.premium_expires_at = expires_at
            await self.session.flush()

        tokens_credited = int(tx.tokens_amount or package.tokens)
        stars_amount = int(tx.stars_amount or package.stars)
        usd_amount_value = float(tx.usd_amount) if tx.usd_amount is not None else None
        logger.info(
            "payment.completed",
            user_id=user.id,
            charge_id=telegram_payment_charge_id,
            package=package.code,
            stars=stars_amount,
            tokens=tokens_credited,
            transaction_id=int(tx.id),
            recurring=is_recurring,
        )
        observe_purchase(
            package=package.code,
            tokens=tokens_credited,
            stars=stars_amount,
            usd=usd_amount_value,
        )
        observe_payment_event(
            event="renewal" if is_recurring else "completed",
            package=package.code,
        )
        return PaymentResult(
            transaction_id=int(tx.id),
            user_id=int(user.id),
            tokens_credited=tokens_credited,
            stars_amount=stars_amount,
            package_code=package.code,
            new_balance=int(user.token_balance or 0),
            is_subscription=package.is_subscription,
            subscription_id=subscription_id,
            expires_at=expires_at,
        )

    # --------------------------------------------------------------- status

    async def get_status(self, *, invoice_id: str, user_id: int) -> PaymentStatus:
        """Return the current status of an invoice owned by ``user_id``.

        ``invoice_id`` is the payload returned by :meth:`create_invoice`.
        """
        stmt = (
            select(Transaction)
            .where(
                Transaction.user_id == user_id,
                Transaction.payment_id.in_(
                    (f"{INVOICE_PREFIX}{invoice_id}",)
                ),
            )
            .limit(1)
        )
        tx = (await self.session.execute(stmt)).scalar_one_or_none()
        if tx is None:
            # Maybe already finalised — fall back to scanning by package + user.
            parts: dict[str, str]
            try:
                parts = parse_payload(invoice_id)
            except InvoicePayloadInvalidError as exc:
                raise InvoiceNotFoundError(
                    f"invoice {invoice_id!r} not found"
                ) from exc
            stmt = (
                select(Transaction)
                .where(
                    Transaction.user_id == user_id,
                    Transaction.package_name == parts.get("pkg"),
                    Transaction.payment_id.like(f"{CHARGE_PREFIX}%"),
                )
                .order_by(Transaction.created_at.desc())
                .limit(1)
            )
            tx = (await self.session.execute(stmt)).scalar_one_or_none()
        if tx is None:
            raise InvoiceNotFoundError(f"invoice {invoice_id!r} not found")

        charge_id: str | None = None
        if tx.payment_id and tx.payment_id.startswith(CHARGE_PREFIX):
            charge_id = tx.payment_id[len(CHARGE_PREFIX) :]
        return PaymentStatus(
            invoice_id=invoice_id,
            status=str(tx.payment_status or "pending"),
            package_code=tx.package_name,
            tokens_credited=int(tx.tokens_amount or 0),
            stars_amount=int(tx.stars_amount or 0) or None,
            transaction_id=int(tx.id),
            created_at=tx.created_at,
            completed_at=tx.completed_at,
            telegram_payment_charge_id=charge_id,
        )

    # -------------------------------------------------------------- helpers

    async def _get_user(self, user_id: int) -> User:
        stmt = select(User).where(User.id == user_id)
        user = (await self.session.execute(stmt)).scalar_one_or_none()
        if user is None:
            raise UserNotFoundError(f"user {user_id} not found")
        return user

    async def _maybe_credit_referral_bonus(
        self,
        *,
        referee: User,
        purchase_transaction_id: int,
    ) -> None:
        """Credit the inviter when ``referee`` completes their first purchase.

        Skipped when:

        * the user has no inviter (``referred_by`` is null);
        * the user already has another completed ``purchase`` transaction
          (this is not the first purchase);
        * a ``referral_bonus`` row already exists for this referee (a
          previous call already credited the inviter — idempotency).
        """
        if not referee.referred_by:
            return

        marker = f"{REFERRAL_BONUS_PREFIX}{referee.id}"
        existing_bonus = await self.session.execute(
            select(Transaction.id).where(Transaction.payment_id == marker)
        )
        if existing_bonus.scalar_one_or_none() is not None:
            return

        # Detect "first purchase" — count completed purchases other than the
        # one we just upgraded.  If this user has a prior completed purchase
        # the referrer was already paid (or should have been).
        prior_stmt = (
            select(Transaction.id)
            .where(
                Transaction.user_id == referee.id,
                Transaction.transaction_type == "purchase",
                Transaction.payment_status == "completed",
                Transaction.id != purchase_transaction_id,
            )
            .limit(1)
        )
        if (await self.session.execute(prior_stmt)).scalar_one_or_none() is not None:
            return

        bonus = self._referral_bonus_amount()
        if bonus <= 0:
            return

        referrer = await self._fetch_referrer(int(referee.referred_by))
        if referrer is None or referrer.is_banned:
            return

        token_service = TokenService(self.session)
        # Wrap the credit in a SAVEPOINT so a race on the partial unique
        # index over ``payment_id`` rolls back only the duplicate insert —
        # not the surrounding payment transaction.
        savepoint = await self.session.begin_nested()
        try:
            credit = await token_service.add(
                user_id=int(referrer.id),
                amount=bonus,
                transaction_type="bonus",
                package_name=REFERRAL_BONUS_PACKAGE,
                payment_id=marker,
                payment_status="completed",
                meta={
                    "referee_user_id": int(referee.id),
                    "purchase_transaction_id": purchase_transaction_id,
                },
            )
        except IntegrityError:
            await savepoint.rollback()
            return
        except UserNotFoundError:
            await savepoint.rollback()
            return
        else:
            await savepoint.commit()

        logger.info(
            "payment.referral_bonus_credited",
            referrer_id=int(referrer.id),
            referee_id=int(referee.id),
            tokens=bonus,
            transaction_id=credit.transaction_id,
            purchase_transaction_id=purchase_transaction_id,
        )

    def _referral_bonus_amount(self) -> int:
        """Read the configured referral bonus, defaulting to 100."""
        try:
            from app.core.config import get_settings

            return int(
                getattr(
                    get_settings(),
                    "telegram_referral_bonus_tokens",
                    DEFAULT_REFERRAL_BONUS_TOKENS,
                )
            )
        except Exception:  # noqa: BLE001 — fall back to the constant
            return DEFAULT_REFERRAL_BONUS_TOKENS

    async def _fetch_referrer(self, user_id: int) -> User | None:
        stmt = select(User).where(User.id == user_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _find_pending_invoice(self, payload: str) -> Transaction | None:
        stmt = (
            select(Transaction)
            .where(
                Transaction.payment_id == f"{INVOICE_PREFIX}{payload}",
                Transaction.payment_status == "pending",
            )
            .with_for_update()
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _find_completed_by_charge_id(
        self, charge_id: str
    ) -> Transaction | None:
        stmt = (
            select(Transaction)
            .where(Transaction.payment_id == f"{CHARGE_PREFIX}{charge_id}")
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def _fetch_transaction(self, transaction_id: int) -> Transaction:
        stmt = select(Transaction).where(Transaction.id == transaction_id)
        tx = (await self.session.execute(stmt)).scalar_one_or_none()
        if tx is None:
            raise PaymentError(f"transaction {transaction_id} not found")
        return tx

    async def _upsert_subscription(
        self,
        *,
        user_id: int,
        package: PaymentPackage,
        transaction_id: int,
    ) -> Subscription:
        """Create-or-extend an active subscription row for the plan.

        On first purchase a fresh row is inserted with ``expires_at = now + days``.
        Subsequent renewals push the existing expiry forward by ``days`` (or
        from "now" if the previous period already lapsed, so a lapsed user
        doesn't keep paying for missed days).
        """
        if not package.is_subscription or package.plan_code is None:
            raise PaymentError(
                f"package {package.code!r} is not a subscription"
            )
        now = datetime.now(UTC)
        days = package.subscription_days or PRO_SUBSCRIPTION_DAYS
        stmt = (
            select(Subscription)
            .where(
                Subscription.user_id == user_id,
                Subscription.plan_code == package.plan_code,
            )
            .order_by(Subscription.expires_at.desc())
            .with_for_update()
            .limit(1)
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is None:
            sub = Subscription(
                user_id=user_id,
                plan_code=package.plan_code,
                starts_at=now,
                expires_at=now + timedelta(days=days),
                auto_renew=True,
                last_transaction_id=transaction_id,
                status="active",
            )
            self.session.add(sub)
            await self.session.flush()
            return sub

        base = existing.expires_at if existing.expires_at > now else now
        existing.expires_at = base + timedelta(days=days)
        existing.last_transaction_id = transaction_id
        existing.status = "active"
        existing.auto_renew = True
        await self.session.flush()
        return existing


# --------------------------------------------------------------- subscription


async def process_subscription_renewals(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[PaymentResult]:
    """Renew subscriptions whose ``expires_at`` has passed.

    Designed to be invoked from a daily Celery beat task (see
    ``docs/ARCHITECTURE.md > Workers``).  For each expired auto-renew
    subscription:

    * credits the next period's tokens via :class:`TokenService.add`;
    * inserts a ``purchase`` transaction tagged
      ``payment_id="renewal:<sub_id>:<period_index>"`` so duplicate runs
      cannot double-credit;
    * pushes ``expires_at`` forward by ``subscription_days``.

    Returns the list of :class:`PaymentResult` rows for each renewal that
    was applied — empty when nothing was due.
    """
    moment = now or datetime.now(UTC)
    stmt = (
        select(Subscription)
        .where(
            Subscription.auto_renew.is_(True),
            Subscription.expires_at <= moment,
            Subscription.status == "active",
        )
        .order_by(Subscription.expires_at.asc())
    )
    if limit is not None:
        stmt = stmt.limit(int(limit))
    subs = list((await session.execute(stmt)).scalars().all())

    token_service = TokenService(session)
    results: list[PaymentResult] = []
    for sub in subs:
        package = _package_for_plan(sub.plan_code)
        if package is None:
            logger.warning(
                "payment.renewal.unknown_plan",
                subscription_id=sub.id,
                plan=sub.plan_code,
            )
            continue
        period_index = await _next_renewal_index(session, sub.id)
        renewal_marker = f"renewal:{sub.id}:{period_index}"
        already = await session.execute(
            select(Transaction.id).where(Transaction.payment_id == renewal_marker)
        )
        if already.scalar_one_or_none() is not None:
            # Defensive: the marker exists but the expiry was not pushed —
            # advance the row and move on.
            sub.expires_at = sub.expires_at + timedelta(days=package.subscription_days)
            await session.flush()
            continue

        try:
            credit = await token_service.add(
                user_id=sub.user_id,
                amount=package.tokens,
                transaction_type="purchase",
                package_name=package.code,
                payment_id=renewal_marker,
                payment_method=PAYMENT_METHOD,
                payment_status="completed",
                stars_amount=package.stars,
                meta={
                    "subscription_id": sub.id,
                    "period_index": period_index,
                    "renewal": True,
                },
            )
        except UserNotFoundError:
            logger.warning(
                "payment.renewal.user_missing",
                subscription_id=sub.id,
                user_id=sub.user_id,
            )
            sub.status = "cancelled"
            sub.auto_renew = False
            await session.flush()
            continue

        sub.expires_at = sub.expires_at + timedelta(days=package.subscription_days)
        sub.last_transaction_id = credit.transaction_id
        await session.flush()

        user = await _fetch_user(session, sub.user_id)
        if user is not None and (
            user.premium_expires_at is None
            or user.premium_expires_at < sub.expires_at
        ):
            user.premium_expires_at = sub.expires_at
            user.is_premium = True
            await session.flush()

        logger.info(
            "payment.renewal.applied",
            subscription_id=sub.id,
            user_id=sub.user_id,
            plan=sub.plan_code,
            transaction_id=credit.transaction_id,
            new_expires_at=sub.expires_at.isoformat(),
        )
        observe_purchase(
            package=package.code,
            tokens=int(package.tokens),
            stars=int(package.stars),
        )
        observe_payment_event(event="renewal", package=package.code)
        results.append(
            PaymentResult(
                transaction_id=int(credit.transaction_id),
                user_id=int(sub.user_id),
                tokens_credited=int(package.tokens),
                stars_amount=int(package.stars),
                package_code=package.code,
                new_balance=int(credit.new_balance),
                is_subscription=True,
                subscription_id=int(sub.id),
                expires_at=sub.expires_at,
            )
        )
    return results


def _package_for_plan(plan_code: str) -> PaymentPackage | None:
    """Return the package object that drives renewals for ``plan_code``."""
    from app.services.payment_packages import PACKAGES

    for pkg in PACKAGES.values():
        if pkg.is_subscription and pkg.plan_code == plan_code:
            return pkg
    return None


async def _next_renewal_index(session: AsyncSession, subscription_id: int) -> int:
    """Return the next 0-based renewal period for ``subscription_id``."""
    stmt = select(Transaction.id).where(
        Transaction.payment_id.like(f"renewal:{subscription_id}:%")
    )
    rows = (await session.execute(stmt)).scalars().all()
    return len(list(rows))


async def _fetch_user(session: AsyncSession, user_id: int) -> User | None:
    return (
        await session.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()


__all__ = [
    "CHARGE_PREFIX",
    "DEFAULT_CURRENCY",
    "INVOICE_PREFIX",
    "InvoiceCreation",
    "InvoiceNotFoundError",
    "InvoicePayloadInvalidError",
    "PAYMENT_METHOD",
    "PackageNotFoundError",
    "PaymentAlreadyProcessedError",
    "PaymentError",
    "PaymentResult",
    "PaymentService",
    "PaymentStatus",
    "parse_payload",
    "process_subscription_renewals",
]
