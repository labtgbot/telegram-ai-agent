"""Token packages available for purchase via Telegram Stars.

The catalog is intentionally a static dict in code for Phase 2 — admins
will be able to override prices via ``admin_settings`` in Phase 3.  Keep
the codes URL-safe; they end up in invoice payloads.

Reference: docs/TOKEN_ECONOMY.md > Packages.
"""
from __future__ import annotations

from dataclasses import dataclass

PRO_PLAN_CODE = "pro"
PRO_SUBSCRIPTION_DAYS = 30


@dataclass(frozen=True)
class PaymentPackage:
    """A purchasable bundle of tokens.

    ``stars`` is the price in Telegram Stars (currency code ``XTR``).
    ``is_subscription`` marks recurring packages whose accrual is
    extended monthly by the renewal worker until cancellation.
    """

    code: str
    title: str
    description: str
    tokens: int
    stars: int
    is_subscription: bool = False
    subscription_days: int = 0
    plan_code: str | None = None


PACKAGES: dict[str, PaymentPackage] = {
    "starter": PaymentPackage(
        code="starter",
        title="Starter",
        description="500 tokens",
        tokens=500,
        stars=250,
    ),
    "basic": PaymentPackage(
        code="basic",
        title="Basic",
        description="1,200 tokens",
        tokens=1200,
        stars=500,
    ),
    "premium": PaymentPackage(
        code="premium",
        title="Premium",
        description="2,000 tokens",
        tokens=2000,
        stars=750,
    ),
    "pro_monthly": PaymentPackage(
        code="pro_monthly",
        title="Pro Monthly",
        description="2,000 tokens every 30 days",
        tokens=2000,
        stars=500,
        is_subscription=True,
        subscription_days=PRO_SUBSCRIPTION_DAYS,
        plan_code=PRO_PLAN_CODE,
    ),
}


def get_package(code: str | None) -> PaymentPackage | None:
    """Return the package matching ``code`` or ``None``."""
    if not code:
        return None
    return PACKAGES.get(code.strip().lower())


def list_packages() -> list[PaymentPackage]:
    """Return all packages in display order (one-time first, sub last)."""
    one_time = [p for p in PACKAGES.values() if not p.is_subscription]
    subs = [p for p in PACKAGES.values() if p.is_subscription]
    return one_time + subs


__all__ = [
    "PACKAGES",
    "PRO_PLAN_CODE",
    "PRO_SUBSCRIPTION_DAYS",
    "PaymentPackage",
    "get_package",
    "list_packages",
]
