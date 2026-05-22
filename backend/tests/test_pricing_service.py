"""Tests for the dynamic pricing service (Phase 3, issue #26).

Layered tests:

1. Pure helpers — validation, defaults, the discount formula.  No DB,
   no FastAPI.
2. DB-backed flow — ``load_pricing_config`` / ``update_pricing_config``
   round-trips through ``admin_settings`` and writes an
   ``admin_audit_logs`` row in the same transaction.  Skipped without
   ``DATABASE_URL``.
3. Active-subscription conflict — verifies the
   ``docs/PRICING_STRATEGY.md > Edge Cases`` rule: a pricing update
   does **not** retroactively change the price billed by the renewal
   worker.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

# Pre-warm ``app.bot`` so ``app.bot.__init__`` finishes loading before
# ``app.services.payments`` is imported here — see
# ``tests/test_referrals.py`` for the same workaround.  Without priming,
# importing ``payments`` directly races with ``app.bot.handlers`` (which
# imports from ``payments``) and trips a circular import on
# ``InvoiceNotFoundError``.
from app.bot.client import TelegramApiError  # noqa: F401
from app.models.admin_audit_log import AdminAuditLog
from app.models.admin_setting import AdminSetting
from app.models.subscription import Subscription
from app.models.transaction import Transaction
from app.models.user import User
from app.services.payment_packages import (
    PACKAGES,
    PRO_PLAN_CODE,
)
from app.services.payments import PaymentService, process_subscription_renewals
from app.services.pricing import (
    DEFAULT_DAILY_BONUS,
    DEFAULT_FIRST_PURCHASE_BONUS,
    DEFAULT_REFERRAL_BONUS,
    MAX_DISCOUNT_PERCENT,
    PRICING_AUDIT_ACTION,
    PRICING_SETTING_KEY,
    InvalidPricingPayloadError,
    PricingConfig,
    PricingPackageOverride,
    PricingUpdateRequest,
    UnknownPackageError,
    apply_pricing_to_package,
    default_pricing_config,
    effective_stars_for,
    effective_tokens_for,
    load_pricing_config,
    update_pricing_config,
)

# =========================================================================
# Pure helpers — no DB.
# =========================================================================


def test_default_config_mirrors_static_catalogue() -> None:
    config = default_pricing_config()
    codes = [pkg.code for pkg in config.packages]
    assert codes == list(PACKAGES.keys())
    starter = config.package_map()["starter"]
    assert starter.tokens == PACKAGES["starter"].tokens
    assert starter.stars == PACKAGES["starter"].stars
    assert starter.discount == 0
    assert config.global_discount == 0
    assert config.seasonal_promo == 0
    assert config.daily_bonus == DEFAULT_DAILY_BONUS
    assert config.referral_bonus == DEFAULT_REFERRAL_BONUS
    assert config.first_purchase_bonus == DEFAULT_FIRST_PURCHASE_BONUS


def test_effective_stars_applies_global_seasonal_and_per_package_discounts() -> None:
    config = PricingConfig(
        packages=(
            PricingPackageOverride(
                code="starter",
                tokens=500,
                stars=250,
                discount=10,
            ),
        ),
        global_discount=20,
        seasonal_promo=5,
    )
    pkg = PACKAGES["starter"]
    # base=250, total discount = 20 + 5 + 10 = 35% → 250 * 0.65 = 162.5 → 162
    assert effective_stars_for(pkg, config) == 162


def test_effective_stars_clamps_to_minimum_one_star() -> None:
    config = PricingConfig(
        packages=(
            PricingPackageOverride(
                code="starter",
                tokens=500,
                stars=1,
                discount=MAX_DISCOUNT_PERCENT,
            ),
        ),
    )
    # Even maxed out, the invoice must charge at least 1 Star.
    assert effective_stars_for(PACKAGES["starter"], config) >= 1


def test_effective_stars_caps_combined_discount_at_max() -> None:
    config = PricingConfig(
        packages=(
            PricingPackageOverride(
                code="starter", tokens=500, stars=250, discount=99
            ),
        ),
        global_discount=99,
        seasonal_promo=99,
    )
    # Sum is well over 100, but the formula caps at 95% so we charge 5%.
    stars = effective_stars_for(PACKAGES["starter"], config)
    assert stars == max(1, (250 * (100 - MAX_DISCOUNT_PERCENT)) // 100)


def test_effective_tokens_uses_override_when_present() -> None:
    config = PricingConfig(
        packages=(
            PricingPackageOverride(
                code="starter", tokens=750, stars=200, discount=0
            ),
        ),
    )
    assert effective_tokens_for(PACKAGES["starter"], config) == 750


def test_apply_pricing_to_package_returns_overridden_copy() -> None:
    config = PricingConfig(
        packages=(
            PricingPackageOverride(
                code="basic", tokens=1500, stars=400, discount=25
            ),
        ),
        global_discount=10,
    )
    updated = apply_pricing_to_package(PACKAGES["basic"], config)
    # tokens always uses the override value as-is
    assert updated.tokens == 1500
    # stars = 400 * (100 - 10 - 25) / 100 = 260
    assert updated.stars == 260
    # static-only fields are preserved
    assert updated.code == "basic"
    assert updated.is_subscription is False


# ---------------------------------------------------------------- validation


def test_update_request_rejects_unknown_package() -> None:
    payload = PricingUpdateRequest(packages={"ghost": {"stars": 1}})
    with pytest.raises(UnknownPackageError):
        from app.services.pricing import _parse_update_payload

        _parse_update_payload(payload, default_pricing_config())


def test_update_request_rejects_discount_over_max() -> None:
    payload = PricingUpdateRequest(
        packages={"starter": {"discount": MAX_DISCOUNT_PERCENT + 1}}
    )
    with pytest.raises(InvalidPricingPayloadError):
        from app.services.pricing import _parse_update_payload

        _parse_update_payload(payload, default_pricing_config())


def test_update_request_rejects_negative_stars() -> None:
    payload = PricingUpdateRequest(packages={"starter": {"stars": -1}})
    with pytest.raises(InvalidPricingPayloadError):
        from app.services.pricing import _parse_update_payload

        _parse_update_payload(payload, default_pricing_config())


def test_update_request_rejects_bool_for_percent() -> None:
    """``isinstance(True, int)`` is True — reject explicitly."""
    payload = PricingUpdateRequest(global_discount=True)
    with pytest.raises(InvalidPricingPayloadError):
        from app.services.pricing import _parse_update_payload

        _parse_update_payload(payload, default_pricing_config())


def test_update_request_inherits_unspecified_fields() -> None:
    from app.services.pricing import _parse_update_payload

    current = PricingConfig(
        packages=tuple(default_pricing_config().packages),
        global_discount=15,
        seasonal_promo=5,
        first_purchase_bonus=25,
        referral_bonus=200,
        daily_bonus=20,
        currency_rate=0.02,
    )
    # Only change one thing.
    new_config = _parse_update_payload(
        PricingUpdateRequest(global_discount=30), current
    )
    assert new_config.global_discount == 30
    assert new_config.seasonal_promo == 5
    assert new_config.first_purchase_bonus == 25
    assert new_config.referral_bonus == 200
    assert new_config.daily_bonus == 20
    assert new_config.currency_rate == 0.02


def test_parse_pricing_value_logs_and_skips_bad_overrides() -> None:
    """Malformed JSON in admin_settings must not break the invoice flow."""
    from app.services.pricing import _parse_pricing_value

    config = _parse_pricing_value(
        {
            "packages": [
                {"code": "starter", "tokens": "not-a-number", "stars": 100},
                {"code": "basic", "tokens": 1500, "stars": 400, "discount": 10},
            ],
            "global_discount": "bogus",
            "seasonal_promo": 7,
        }
    )
    # bad package skipped, good one applied
    overrides = config.package_map()
    assert overrides["starter"].tokens == PACKAGES["starter"].tokens  # fallback
    assert overrides["basic"].tokens == 1500
    assert overrides["basic"].discount == 10
    # bad global_discount falls back to default
    assert config.global_discount == 0
    assert config.seasonal_promo == 7


def test_parse_pricing_value_handles_packages_as_object_map() -> None:
    """Older clients may send packages as ``{code: {...}}`` instead of list."""
    from app.services.pricing import _parse_pricing_value

    config = _parse_pricing_value(
        {
            "packages": {
                "starter": {"tokens": 600, "stars": 220, "discount": 5},
            },
        }
    )
    starter = config.package_map()["starter"]
    assert starter.tokens == 600
    assert starter.stars == 220
    assert starter.discount == 5


# =========================================================================
# DB integration — real Postgres.
# =========================================================================


async def _make_admin(session, *, telegram_id: int, code: str) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"adm{telegram_id}",
        referral_code=code,
        role="super_admin",
        token_balance=0,
    )
    session.add(user)
    await session.flush()
    return user


async def _make_user(session, *, telegram_id: int, code: str) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"u{telegram_id}",
        referral_code=code,
        token_balance=0,
    )
    session.add(user)
    await session.flush()
    return user


def _fake_telegram_client(invoice_link: str = "https://t.me/$x") -> Any:
    client = AsyncMock()
    client.create_invoice_link = AsyncMock(return_value=invoice_link)
    return client


@pytest.mark.asyncio
async def test_load_pricing_config_returns_defaults_when_no_row(db_session) -> None:
    config = await load_pricing_config(db_session)
    assert config.global_discount == 0
    assert [p.code for p in config.packages] == list(PACKAGES.keys())
    # No row was created as a side effect — load is read-only.
    row = (
        await db_session.execute(
            select(AdminSetting).where(AdminSetting.setting_key == PRICING_SETTING_KEY)
        )
    ).scalar_one_or_none()
    assert row is None


@pytest.mark.asyncio
async def test_update_pricing_config_persists_and_writes_audit(db_session) -> None:
    admin = await _make_admin(db_session, telegram_id=9_400_001, code="PR-AUD-1")
    payload = PricingUpdateRequest(
        packages={"starter": {"stars": 200, "tokens": 600, "discount": 5}},
        global_discount=10,
        seasonal_promo=3,
    )
    result = await update_pricing_config(
        db_session,
        admin=admin,
        payload=payload,
        ip_address="1.2.3.4",
        user_agent="pytest",
    )

    # Returned config reflects the update.
    starter = result.config.package_map()["starter"]
    assert starter.stars == 200
    assert starter.tokens == 600
    assert starter.discount == 5
    assert result.config.global_discount == 10
    assert result.config.seasonal_promo == 3

    # admin_settings row exists and is JSON-shaped.
    row = (
        await db_session.execute(
            select(AdminSetting).where(AdminSetting.setting_key == PRICING_SETTING_KEY)
        )
    ).scalar_one()
    assert isinstance(row.setting_value, dict)
    assert row.updated_by == admin.id
    payload_stored = row.setting_value
    assert payload_stored["global_discount"] == 10
    assert payload_stored["seasonal_promo"] == 3

    # Audit log row was written in the same transaction.
    log = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.id == result.audit_log_id)
        )
    ).scalar_one()
    assert log.action == PRICING_AUDIT_ACTION
    assert log.admin_id == admin.id
    assert log.ip_address == "1.2.3.4"
    assert log.user_agent == "pytest"
    assert "diff" in log.payload
    assert "config" in log.payload


@pytest.mark.asyncio
async def test_update_pricing_config_second_write_updates_in_place(db_session) -> None:
    admin = await _make_admin(db_session, telegram_id=9_400_002, code="PR-AUD-2")
    await update_pricing_config(
        db_session,
        admin=admin,
        payload=PricingUpdateRequest(global_discount=10),
    )
    await update_pricing_config(
        db_session,
        admin=admin,
        payload=PricingUpdateRequest(global_discount=25),
    )

    rows = (
        await db_session.execute(
            select(AdminSetting).where(AdminSetting.setting_key == PRICING_SETTING_KEY)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].setting_value["global_discount"] == 25

    audits = (
        await db_session.execute(
            select(AdminAuditLog).where(AdminAuditLog.action == PRICING_AUDIT_ACTION)
        )
    ).scalars().all()
    # Two audit rows, both filed by the same admin.
    assert len(audits) == 2
    assert {a.admin_id for a in audits} == {admin.id}


@pytest.mark.asyncio
async def test_update_pricing_config_rejects_unknown_package(db_session) -> None:
    admin = await _make_admin(db_session, telegram_id=9_400_003, code="PR-AUD-3")
    with pytest.raises(UnknownPackageError):
        await update_pricing_config(
            db_session,
            admin=admin,
            payload=PricingUpdateRequest(packages={"ghost": {"stars": 1}}),
        )


@pytest.mark.asyncio
async def test_load_pricing_config_round_trips_through_admin_settings(
    db_session,
) -> None:
    admin = await _make_admin(db_session, telegram_id=9_400_004, code="PR-RT-1")
    await update_pricing_config(
        db_session,
        admin=admin,
        payload=PricingUpdateRequest(
            packages={"basic": {"stars": 350, "tokens": 1500, "discount": 12}},
            global_discount=5,
        ),
    )

    config = await load_pricing_config(db_session)
    basic = config.package_map()["basic"]
    assert basic.stars == 350
    assert basic.tokens == 1500
    assert basic.discount == 12
    assert config.global_discount == 5


# =========================================================================
# Discount → invoice integration
# =========================================================================


@pytest.mark.asyncio
async def test_create_invoice_applies_admin_discount_to_pending_row(
    db_session,
) -> None:
    """The pending Transaction stores the *effective* stars price."""
    admin = await _make_admin(db_session, telegram_id=9_400_010, code="PR-INV-1")
    customer = await _make_user(db_session, telegram_id=9_400_011, code="PR-INV-2")

    # Cut starter from 250⭐ → 200⭐ via a per-package override, plus 10% global.
    await update_pricing_config(
        db_session,
        admin=admin,
        payload=PricingUpdateRequest(
            packages={"starter": {"stars": 200, "tokens": 500}},
            global_discount=10,
        ),
    )

    client = _fake_telegram_client()
    svc = PaymentService(db_session, client=client)
    invoice = await svc.create_invoice(user_id=customer.id, package_code="starter")

    # 200 * (100 - 10) / 100 = 180
    assert invoice.stars_amount == 180
    assert invoice.tokens_amount == 500

    # Pending row mirrors what we quoted Telegram.
    pending = (
        await db_session.execute(
            select(Transaction).where(Transaction.id == invoice.transaction_id)
        )
    ).scalar_one()
    assert pending.stars_amount == 180
    assert pending.tokens_amount == 500

    # The Telegram client was asked for the discounted price.
    create_call = client.create_invoice_link.call_args
    prices = create_call.kwargs["prices"]
    assert prices[0]["amount"] == 180


@pytest.mark.asyncio
async def test_invoice_price_is_locked_after_quoting(db_session) -> None:
    """Changing pricing *after* an invoice is issued must not break it.

    The pre_checkout webhook validates ``total_amount`` against the
    pending row — the value the user actually saw — not whatever the
    catalogue currently says.
    """
    admin = await _make_admin(db_session, telegram_id=9_400_020, code="PR-LOCK-1")
    customer = await _make_user(db_session, telegram_id=9_400_021, code="PR-LOCK-2")

    # Quote at the default price (250⭐).
    client = _fake_telegram_client()
    svc = PaymentService(db_session, client=client)
    invoice = await svc.create_invoice(user_id=customer.id, package_code="starter")
    assert invoice.stars_amount == 250

    # Now admin slashes prices — but the quoted invoice should still
    # accept exactly 250⭐ at pre_checkout time.
    await update_pricing_config(
        db_session,
        admin=admin,
        payload=PricingUpdateRequest(global_discount=50),
    )

    package = await svc.confirm_pre_checkout(
        payload=invoice.payload,
        total_amount=250,
        currency="XTR",
    )
    assert package.code == "starter"


@pytest.mark.asyncio
async def test_subscription_renewal_does_not_recalculate_after_price_change(
    db_session,
) -> None:
    """Phase-3 acceptance criterion: an *active* subscription is billed
    against the locked plan price.  A pricing update must not change
    the tokens credited or the stars amount on the renewal row.
    """
    admin = await _make_admin(db_session, telegram_id=9_400_030, code="PR-SUB-1")
    customer = await _make_user(db_session, telegram_id=9_400_031, code="PR-SUB-2")

    # Active-but-expired pro subscription, ready to renew.
    now = datetime.now(UTC)
    sub = Subscription(
        user_id=customer.id,
        plan_code=PRO_PLAN_CODE,
        starts_at=now - timedelta(days=30),
        expires_at=now - timedelta(hours=1),
        auto_renew=True,
        status="active",
    )
    db_session.add(sub)
    await db_session.flush()

    # Admin halves the Pro price + halves the tokens AFTER the sub is active.
    await update_pricing_config(
        db_session,
        admin=admin,
        payload=PricingUpdateRequest(
            packages={
                "pro_monthly": {"stars": 250, "tokens": 1000, "discount": 0}
            },
            global_discount=0,
        ),
    )

    results = await process_subscription_renewals(db_session)
    assert len(results) == 1
    renewal = results[0]

    # The renewal still credits the ORIGINAL Pro plan size, not the
    # cheapened version.  The pricing config update was not retroactive.
    assert renewal.tokens_credited == PACKAGES["pro_monthly"].tokens
    assert renewal.stars_amount == PACKAGES["pro_monthly"].stars

    # And the user's balance reflects the locked-in plan.
    await db_session.refresh(customer)
    assert customer.token_balance == PACKAGES["pro_monthly"].tokens
