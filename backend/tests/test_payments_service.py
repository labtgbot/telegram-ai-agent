"""Database-backed integration tests for :class:`PaymentService`.

Exercises the full happy path, idempotency guarantees and the
subscription renewal worker against a real PostgreSQL session (the
``db_session`` fixture from ``conftest.py``).  Tests skip cleanly when
``DATABASE_URL`` is not set.

Acceptance criteria covered:

* ``create_invoice`` writes a pending ``Transaction`` row and calls
  Telegram's ``createInvoiceLink``.
* ``confirm_pre_checkout`` accepts a matching payload and rejects every
  failure mode the issue enumerates (wrong currency, unknown package,
  stars mismatch, missing invoice).
* ``finalize_successful_payment`` credits tokens, upgrades the pending
  row, and is idempotent on the ``telegram_payment_charge_id`` — a
  duplicate webhook must not double-credit.
* ``get_status`` reflects pending → completed transitions.
* Pro subscriptions create an active :class:`Subscription` whose
  ``expires_at`` is roughly ``now + 30d`` and bump
  ``users.premium_expires_at``.
* ``process_subscription_renewals`` credits the next period's tokens
  via a ``renewal:<sub_id>:<period_index>`` payment-id marker and is
  itself idempotent across reruns.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.bot.client import TelegramApiError
from app.models import Transaction, User
from app.models.subscription import Subscription
from app.services.payment_packages import (
    PACKAGES,
    PRO_PLAN_CODE,
    PRO_SUBSCRIPTION_DAYS,
)
from app.services.payments import (
    CHARGE_PREFIX,
    DEFAULT_CURRENCY,
    INVOICE_PREFIX,
    InvoiceNotFoundError,
    InvoicePayloadInvalidError,
    PackageNotFoundError,
    PaymentService,
    parse_payload,
    process_subscription_renewals,
)

# ----------------------------------------------------------------- helpers


async def _make_user(
    session,
    *,
    telegram_id: int,
    code: str,
    balance: int = 0,
) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"u{telegram_id}",
        referral_code=code,
        token_balance=balance,
    )
    session.add(user)
    await session.flush()
    return user


def _fake_client(invoice_link: str = "https://t.me/$test-link") -> Any:
    client = AsyncMock()
    client.create_invoice_link = AsyncMock(return_value=invoice_link)
    client.send_invoice = AsyncMock(return_value={"message_id": 1})
    client.answer_pre_checkout_query = AsyncMock(return_value=True)
    return client


# ----------------------------------------------------------------- parse_payload


def test_parse_payload_round_trips() -> None:
    parts = parse_payload("pkg=starter;u=42;n=abc")
    assert parts["pkg"] == "starter"
    assert parts["u"] == "42"
    assert parts["n"] == "abc"


def test_parse_payload_rejects_empty() -> None:
    with pytest.raises(InvoicePayloadInvalidError):
        parse_payload("")


def test_parse_payload_rejects_malformed() -> None:
    with pytest.raises(InvoicePayloadInvalidError):
        parse_payload("pkg-starter")  # missing '='


def test_parse_payload_rejects_missing_required_fields() -> None:
    with pytest.raises(InvoicePayloadInvalidError):
        parse_payload("n=abc")  # no pkg/u


# ----------------------------------------------------------------- create_invoice


@pytest.mark.asyncio
async def test_create_invoice_writes_pending_row_and_returns_link(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_001, code="PAY-CI-1"
    )
    client = _fake_client(invoice_link="https://t.me/$pending-1")
    svc = PaymentService(db_session, client=client)

    invoice = await svc.create_invoice(user_id=user.id, package_code="starter")

    assert invoice.package_code == "starter"
    assert invoice.stars_amount == 250
    assert invoice.tokens_amount == 500
    assert invoice.telegram_invoice_link == "https://t.me/$pending-1"
    assert invoice.is_subscription is False
    assert client.create_invoice_link.await_count == 1

    call = client.create_invoice_link.await_args
    assert call.kwargs["currency"] == DEFAULT_CURRENCY
    assert call.kwargs["prices"] == [{"label": "Starter", "amount": 250}]
    assert call.kwargs["subscription_period"] is None

    pending = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == invoice.transaction_id)
        )
    ).scalar_one()
    assert pending.payment_status == "pending"
    assert pending.payment_id == f"{INVOICE_PREFIX}{invoice.payload}"
    assert pending.tokens_amount == 500
    assert pending.stars_amount == 250


@pytest.mark.asyncio
async def test_create_invoice_for_subscription_sets_period(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_002, code="PAY-CI-2"
    )
    client = _fake_client(invoice_link="https://t.me/$sub-link")
    svc = PaymentService(db_session, client=client)

    invoice = await svc.create_invoice(
        user_id=user.id, package_code="pro_monthly"
    )

    assert invoice.is_subscription is True
    call = client.create_invoice_link.await_args
    assert call.kwargs["subscription_period"] == PRO_SUBSCRIPTION_DAYS * 24 * 3600


@pytest.mark.asyncio
async def test_create_invoice_unknown_package_raises(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_003, code="PAY-CI-3"
    )
    svc = PaymentService(db_session, client=_fake_client())
    with pytest.raises(PackageNotFoundError):
        await svc.create_invoice(user_id=user.id, package_code="ghost-pack")


@pytest.mark.asyncio
async def test_create_invoice_rolls_back_pending_when_telegram_fails(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_004, code="PAY-CI-4"
    )
    client = _fake_client()
    client.create_invoice_link = AsyncMock(
        side_effect=TelegramApiError("createInvoiceLink", "down")
    )
    svc = PaymentService(db_session, client=client)
    with pytest.raises(TelegramApiError):
        await svc.create_invoice(user_id=user.id, package_code="basic")

    pending_count = (
        await db_session.execute(
            select(Transaction).where(Transaction.user_id == user.id)
        )
    ).scalars().all()
    assert pending_count == []


# ----------------------------------------------------------------- pre_checkout


@pytest.mark.asyncio
async def test_confirm_pre_checkout_accepts_matching_payload(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_005, code="PAY-PC-1"
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=user.id, package_code="starter")
    pkg = await svc.confirm_pre_checkout(
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
    )
    assert pkg.code == "starter"


@pytest.mark.asyncio
async def test_confirm_pre_checkout_rejects_wrong_currency(db_session):
    svc = PaymentService(db_session, client=_fake_client())
    with pytest.raises(InvoicePayloadInvalidError):
        await svc.confirm_pre_checkout(
            payload="pkg=starter;u=1;n=x",
            total_amount=250,
            currency="USD",
        )


@pytest.mark.asyncio
async def test_confirm_pre_checkout_rejects_unknown_package(db_session):
    svc = PaymentService(db_session, client=_fake_client())
    with pytest.raises(PackageNotFoundError):
        await svc.confirm_pre_checkout(
            payload="pkg=phantom;u=1;n=x",
            total_amount=250,
            currency=DEFAULT_CURRENCY,
        )


@pytest.mark.asyncio
async def test_confirm_pre_checkout_rejects_stars_mismatch(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_006, code="PAY-PC-2"
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=user.id, package_code="starter")
    with pytest.raises(InvoicePayloadInvalidError):
        await svc.confirm_pre_checkout(
            payload=invoice.payload,
            total_amount=1,  # not the package price
            currency=DEFAULT_CURRENCY,
        )


@pytest.mark.asyncio
async def test_confirm_pre_checkout_rejects_missing_invoice(db_session):
    svc = PaymentService(db_session, client=_fake_client())
    # No create_invoice call → no pending row exists for the given payload.
    with pytest.raises(InvoiceNotFoundError):
        await svc.confirm_pre_checkout(
            payload="pkg=starter;u=999;n=missing",
            total_amount=250,
            currency=DEFAULT_CURRENCY,
        )


@pytest.mark.asyncio
async def test_confirm_pre_checkout_allows_subscription_without_pending(db_session):
    """Telegram Stars subscriptions renew without re-creating an invoice."""
    svc = PaymentService(db_session, client=_fake_client())
    pkg = await svc.confirm_pre_checkout(
        payload="pkg=pro_monthly;u=1;n=auto",
        total_amount=PACKAGES["pro_monthly"].stars,
        currency=DEFAULT_CURRENCY,
    )
    assert pkg.is_subscription


# ------------------------------------------------- finalize_successful_payment


@pytest.mark.asyncio
async def test_finalize_credits_tokens_and_upgrades_pending_row(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_010, code="PAY-FZ-1", balance=10
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=user.id, package_code="basic")

    result = await svc.finalize_successful_payment(
        telegram_user_id=user.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-basic-1",
    )

    assert result.tokens_credited == 1200
    assert result.new_balance == 10 + 1200
    assert result.is_subscription is False
    assert result.already_processed is False

    await db_session.refresh(user)
    assert user.token_balance == 10 + 1200
    assert user.total_tokens_purchased == 1200

    tx = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == result.transaction_id)
        )
    ).scalar_one()
    assert tx.payment_status == "completed"
    assert tx.payment_id == f"{CHARGE_PREFIX}charge-basic-1"
    assert tx.completed_at is not None
    # Only one row exists for this purchase — the pending row was upgraded.
    rows = (
        await db_session.execute(
            select(Transaction).where(Transaction.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_finalize_is_idempotent_on_duplicate_webhook(db_session):
    """Duplicate ``successful_payment`` deliveries must not double-credit."""
    user = await _make_user(
        db_session, telegram_id=9_000_011, code="PAY-FZ-2"
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=user.id, package_code="starter")
    charge_id = "charge-dup-1"

    first = await svc.finalize_successful_payment(
        telegram_user_id=user.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id=charge_id,
    )
    assert first.already_processed is False
    assert first.tokens_credited == 500

    await db_session.refresh(user)
    balance_after_first = user.token_balance

    second = await svc.finalize_successful_payment(
        telegram_user_id=user.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id=charge_id,
    )
    assert second.already_processed is True
    assert second.transaction_id == first.transaction_id

    await db_session.refresh(user)
    assert user.token_balance == balance_after_first  # no double credit

    rows = (
        await db_session.execute(
            select(Transaction).where(Transaction.user_id == user.id)
        )
    ).scalars().all()
    assert len(rows) == 1  # still just the upgraded pending row


@pytest.mark.asyncio
async def test_finalize_rejects_wrong_currency(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_012, code="PAY-FZ-3"
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=user.id, package_code="starter")
    with pytest.raises(InvoicePayloadInvalidError):
        await svc.finalize_successful_payment(
            telegram_user_id=user.telegram_id,
            payload=invoice.payload,
            total_amount=invoice.stars_amount,
            currency="USD",
            telegram_payment_charge_id="charge-currency",
        )


@pytest.mark.asyncio
async def test_finalize_rejects_stars_mismatch(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_013, code="PAY-FZ-4"
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=user.id, package_code="starter")
    with pytest.raises(InvoicePayloadInvalidError):
        await svc.finalize_successful_payment(
            telegram_user_id=user.telegram_id,
            payload=invoice.payload,
            total_amount=invoice.stars_amount + 1,
            currency=DEFAULT_CURRENCY,
            telegram_payment_charge_id="charge-mismatch",
        )


@pytest.mark.asyncio
async def test_finalize_rejects_unknown_package(db_session):
    """A payload referencing a deleted package short-circuits before crediting."""
    svc = PaymentService(db_session, client=_fake_client())
    with pytest.raises(PackageNotFoundError):
        await svc.finalize_successful_payment(
            telegram_user_id=1,
            payload="pkg=ghost;u=1;n=x",
            total_amount=250,
            currency=DEFAULT_CURRENCY,
            telegram_payment_charge_id="charge-unknown",
        )


# ----------------------------------------------------------- subscription path


@pytest.mark.asyncio
async def test_finalize_subscription_creates_active_subscription(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_020, code="PAY-SUB-1"
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(
        user_id=user.id, package_code="pro_monthly"
    )

    result = await svc.finalize_successful_payment(
        telegram_user_id=user.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-sub-1",
    )
    assert result.is_subscription is True
    assert result.subscription_id is not None
    assert result.expires_at is not None

    sub = (
        await db_session.execute(
            select(Subscription).where(Subscription.id == result.subscription_id)
        )
    ).scalar_one()
    assert sub.plan_code == PRO_PLAN_CODE
    assert sub.auto_renew is True
    assert sub.status == "active"
    delta = sub.expires_at - datetime.now(UTC)
    assert timedelta(days=29) < delta <= timedelta(days=30)

    await db_session.refresh(user)
    assert user.is_premium is True
    assert user.premium_expires_at is not None


@pytest.mark.asyncio
async def test_finalize_subscription_renewal_extends_existing(db_session):
    """A second purchase pushes expires_at forward another period."""
    user = await _make_user(
        db_session, telegram_id=9_000_021, code="PAY-SUB-2"
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice1 = await svc.create_invoice(
        user_id=user.id, package_code="pro_monthly"
    )
    first = await svc.finalize_successful_payment(
        telegram_user_id=user.telegram_id,
        payload=invoice1.payload,
        total_amount=invoice1.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-sub-r1",
    )
    initial_expiry = first.expires_at
    assert initial_expiry is not None

    # Second purchase (a fresh invoice → fresh payload + fresh charge id).
    invoice2 = await svc.create_invoice(
        user_id=user.id, package_code="pro_monthly"
    )
    second = await svc.finalize_successful_payment(
        telegram_user_id=user.telegram_id,
        payload=invoice2.payload,
        total_amount=invoice2.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-sub-r2",
    )
    assert second.subscription_id == first.subscription_id
    assert second.expires_at is not None
    assert second.expires_at > initial_expiry


# ------------------------------------------------------------------ get_status


@pytest.mark.asyncio
async def test_get_status_pending_then_completed(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_030, code="PAY-ST-1"
    )
    svc = PaymentService(db_session, client=_fake_client())
    invoice = await svc.create_invoice(user_id=user.id, package_code="starter")

    pending = await svc.get_status(invoice_id=invoice.payload, user_id=user.id)
    assert pending.status == "pending"
    assert pending.tokens_credited == 500  # tokens_amount on the pending row
    assert pending.telegram_payment_charge_id is None

    await svc.finalize_successful_payment(
        telegram_user_id=user.telegram_id,
        payload=invoice.payload,
        total_amount=invoice.stars_amount,
        currency=DEFAULT_CURRENCY,
        telegram_payment_charge_id="charge-status-1",
    )

    completed = await svc.get_status(invoice_id=invoice.payload, user_id=user.id)
    assert completed.status == "completed"
    assert completed.telegram_payment_charge_id == "charge-status-1"


@pytest.mark.asyncio
async def test_get_status_unknown_invoice_raises(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_031, code="PAY-ST-2"
    )
    svc = PaymentService(db_session, client=_fake_client())
    with pytest.raises(InvoiceNotFoundError):
        await svc.get_status(
            invoice_id="pkg=starter;u=999;n=ghost",
            user_id=user.id,
        )


# ----------------------------------------------------- renewal worker


@pytest.mark.asyncio
async def test_process_subscription_renewals_credits_next_period(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_040, code="PAY-REN-1"
    )
    # Bootstrap an "active" but expired subscription.
    now = datetime.now(UTC)
    expired_at = now - timedelta(hours=1)
    sub = Subscription(
        user_id=user.id,
        plan_code=PRO_PLAN_CODE,
        starts_at=expired_at - timedelta(days=30),
        expires_at=expired_at,
        auto_renew=True,
        status="active",
    )
    db_session.add(sub)
    await db_session.flush()

    results = await process_subscription_renewals(db_session)
    assert len(results) == 1
    renewal = results[0]
    assert renewal.subscription_id == sub.id
    assert renewal.is_subscription is True
    assert renewal.tokens_credited == PACKAGES["pro_monthly"].tokens

    await db_session.refresh(user)
    assert user.token_balance == PACKAGES["pro_monthly"].tokens
    assert user.is_premium is True

    await db_session.refresh(sub)
    assert sub.expires_at > now

    tx = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == renewal.transaction_id)
        )
    ).scalar_one()
    assert tx.payment_id == f"renewal:{sub.id}:0"
    assert tx.payment_status == "completed"
    assert tx.transaction_type == "purchase"


@pytest.mark.asyncio
async def test_process_subscription_renewals_skips_future_expiry(db_session):
    """Active subscriptions whose expires_at is in the future are left alone."""
    user = await _make_user(
        db_session, telegram_id=9_000_041, code="PAY-REN-2"
    )
    now = datetime.now(UTC)
    sub = Subscription(
        user_id=user.id,
        plan_code=PRO_PLAN_CODE,
        starts_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=1),
        auto_renew=True,
        status="active",
    )
    db_session.add(sub)
    await db_session.flush()

    results = await process_subscription_renewals(db_session)
    assert results == []


@pytest.mark.asyncio
async def test_process_subscription_renewals_is_idempotent_across_runs(db_session):
    """A second call without advancing time finds no fresh work to do."""
    user = await _make_user(
        db_session, telegram_id=9_000_042, code="PAY-REN-3"
    )
    expired_at = datetime.now(UTC) - timedelta(hours=1)
    sub = Subscription(
        user_id=user.id,
        plan_code=PRO_PLAN_CODE,
        starts_at=expired_at - timedelta(days=30),
        expires_at=expired_at,
        auto_renew=True,
        status="active",
    )
    db_session.add(sub)
    await db_session.flush()

    first_pass = await process_subscription_renewals(db_session)
    assert len(first_pass) == 1
    # The renewal extended expires_at by 30 days, so the next pass shouldn't
    # touch the subscription again.
    second_pass = await process_subscription_renewals(db_session)
    assert second_pass == []


@pytest.mark.asyncio
async def test_process_subscription_renewals_ignores_cancelled(db_session):
    user = await _make_user(
        db_session, telegram_id=9_000_043, code="PAY-REN-4"
    )
    expired_at = datetime.now(UTC) - timedelta(hours=1)
    sub = Subscription(
        user_id=user.id,
        plan_code=PRO_PLAN_CODE,
        starts_at=expired_at - timedelta(days=30),
        expires_at=expired_at,
        auto_renew=False,  # opted out
        status="active",
    )
    db_session.add(sub)
    await db_session.flush()

    results = await process_subscription_renewals(db_session)
    assert results == []
