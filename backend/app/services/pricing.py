"""Dynamic pricing configuration (Phase 3, issue #26).

Stores per-package overrides, global discount and seasonal promo inside
the ``admin_settings`` JSONB row keyed ``pricing``.  The static
:mod:`app.services.payment_packages` catalogue acts as the source of
truth for what packages *exist*; this layer only changes their price /
discount / tokens at runtime.

A change takes effect on the very next call to :func:`load_pricing_config`,
so a fresh ``create_invoice`` reflects the new price within milliseconds.
Active subscription renewals never go through this code path — they bill
against the locked price recorded on the subscription's last transaction,
which is exactly the behaviour described in ``docs/PRICING_STRATEGY.md >
Edge Cases``.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from time import monotonic
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.admin_audit_log import AdminAuditLog
from app.models.admin_setting import AdminSetting
from app.models.user import User
from app.services.payment_packages import PACKAGES, PaymentPackage

logger = get_logger(__name__)


# ----------------------------------------------------------------- constants

PRICING_SETTING_KEY: Final[str] = "pricing"
PRICING_AUDIT_ACTION: Final[str] = "pricing.update"

MAX_DISCOUNT_PERCENT: Final[int] = 95
MAX_TOKENS_PER_PACKAGE: Final[int] = 10_000_000
MAX_STARS_PER_PACKAGE: Final[int] = 1_000_000
MIN_STARS_PER_PACKAGE: Final[int] = 1
MAX_BONUS_TOKENS: Final[int] = 100_000

# Defaults pulled from PRICING_STRATEGY.md so the API can report a config
# even before an admin has ever opened the editor.
DEFAULT_GLOBAL_DISCOUNT: Final[int] = 0
DEFAULT_SEASONAL_PROMO: Final[int] = 0
DEFAULT_FIRST_PURCHASE_BONUS: Final[int] = 20
DEFAULT_REFERRAL_BONUS: Final[int] = 100
DEFAULT_DAILY_BONUS: Final[int] = 10
DEFAULT_CURRENCY_RATE: Final[float] = 0.013


# ----------------------------------------------------------------- exceptions


class PricingError(Exception):
    """Base class for pricing service errors."""


class InvalidPricingPayloadError(PricingError):
    """Raised when the update payload is structurally invalid."""


class UnknownPackageError(PricingError):
    """Raised when an override references a package that is not in code."""


# --------------------------------------------------------------- data types


@dataclass(frozen=True)
class PricingPackageOverride:
    """Override applied on top of the static :class:`PaymentPackage`.

    Each field is optional in the JSONB blob; missing fields fall back to
    the static value.  ``discount`` is a per-package percentage (0–95)
    applied multiplicatively after the global + seasonal modifiers.
    """

    code: str
    tokens: int
    stars: int
    discount: int = 0
    is_subscription: bool = False
    title: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "tokens": int(self.tokens),
            "stars": int(self.stars),
            "discount": int(self.discount),
            "is_subscription": bool(self.is_subscription),
            "title": self.title,
            "description": self.description,
        }


@dataclass(frozen=True)
class PricingConfig:
    """Snapshot of admin-controlled pricing."""

    packages: tuple[PricingPackageOverride, ...]
    global_discount: int = DEFAULT_GLOBAL_DISCOUNT
    seasonal_promo: int = DEFAULT_SEASONAL_PROMO
    first_purchase_bonus: int = DEFAULT_FIRST_PURCHASE_BONUS
    referral_bonus: int = DEFAULT_REFERRAL_BONUS
    daily_bonus: int = DEFAULT_DAILY_BONUS
    currency_rate: float = DEFAULT_CURRENCY_RATE

    def package_map(self) -> dict[str, PricingPackageOverride]:
        return {p.code: p for p in self.packages}

    def to_dict(self) -> dict[str, Any]:
        return {
            "packages": [p.to_dict() for p in self.packages],
            "global_discount": int(self.global_discount),
            "seasonal_promo": int(self.seasonal_promo),
            "first_purchase_bonus": int(self.first_purchase_bonus),
            "referral_bonus": int(self.referral_bonus),
            "daily_bonus": int(self.daily_bonus),
            "currency_rate": float(self.currency_rate),
        }


# --------------------------------------------------------------- helpers


def _coerce_percent(value: Any, *, field_name: str, max_value: int = MAX_DISCOUNT_PERCENT) -> int:
    if isinstance(value, bool):
        raise InvalidPricingPayloadError(f"{field_name} must be an integer percent")
    if value is None:
        return 0
    try:
        intval = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidPricingPayloadError(
            f"{field_name} must be an integer percent"
        ) from exc
    if intval < 0 or intval > max_value:
        raise InvalidPricingPayloadError(
            f"{field_name} must be between 0 and {max_value}"
        )
    return intval


def _coerce_int(value: Any, *, field_name: str, min_value: int, max_value: int) -> int:
    if isinstance(value, bool):
        raise InvalidPricingPayloadError(f"{field_name} must be an integer")
    if value is None:
        return min_value
    try:
        intval = int(value)
    except (TypeError, ValueError) as exc:
        raise InvalidPricingPayloadError(f"{field_name} must be an integer") from exc
    if intval < min_value or intval > max_value:
        raise InvalidPricingPayloadError(
            f"{field_name} must be between {min_value} and {max_value}"
        )
    return intval


def _coerce_currency_rate(value: Any) -> float:
    if value is None:
        return DEFAULT_CURRENCY_RATE
    try:
        rate = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidPricingPayloadError("currency_rate must be a number") from exc
    if rate < 0 or rate > 1000:
        raise InvalidPricingPayloadError("currency_rate must be between 0 and 1000")
    return round(rate, 6)


def _default_override(package: PaymentPackage) -> PricingPackageOverride:
    return PricingPackageOverride(
        code=package.code,
        tokens=package.tokens,
        stars=package.stars,
        discount=0,
        is_subscription=package.is_subscription,
        title=package.title,
        description=package.description,
    )


def _parse_package_entry(
    code: str,
    raw: Mapping[str, Any],
) -> PricingPackageOverride:
    static = PACKAGES.get(code)
    if static is None:
        raise UnknownPackageError(f"unknown package: {code!r}")
    tokens = _coerce_int(
        raw.get("tokens", static.tokens),
        field_name=f"packages[{code}].tokens",
        min_value=1,
        max_value=MAX_TOKENS_PER_PACKAGE,
    )
    stars = _coerce_int(
        raw.get("stars", static.stars),
        field_name=f"packages[{code}].stars",
        min_value=MIN_STARS_PER_PACKAGE,
        max_value=MAX_STARS_PER_PACKAGE,
    )
    discount = _coerce_percent(
        raw.get("discount", 0), field_name=f"packages[{code}].discount"
    )
    return PricingPackageOverride(
        code=code,
        tokens=tokens,
        stars=stars,
        discount=discount,
        is_subscription=static.is_subscription,
        title=static.title,
        description=static.description,
    )


def _merge_packages(
    overrides: Iterable[PricingPackageOverride],
) -> tuple[PricingPackageOverride, ...]:
    """Combine code-defined packages with admin overrides.

    Order is preserved from :data:`PACKAGES` so the UI always renders the
    static catalogue in a stable sequence even when an admin override
    leaves some packages untouched.
    """
    override_map = {p.code: p for p in overrides}
    merged: list[PricingPackageOverride] = []
    for code, pkg in PACKAGES.items():
        merged.append(override_map.get(code, _default_override(pkg)))
    return tuple(merged)


def _parse_pricing_value(raw: Any) -> PricingConfig:
    """Best-effort parser used by :func:`load_pricing_config`.

    Returns a default config when ``raw`` is missing or malformed and logs
    a warning — never raises, because a config-read should not break the
    invoice flow.
    """
    if not isinstance(raw, Mapping):
        return default_pricing_config()

    overrides: list[PricingPackageOverride] = []
    packages_raw = raw.get("packages")
    if isinstance(packages_raw, Mapping):
        iterable: Iterable[tuple[str, Any]] = packages_raw.items()
    elif isinstance(packages_raw, list):
        iterable = (
            (str(item.get("code")), item)
            for item in packages_raw
            if isinstance(item, Mapping) and item.get("code")
        )
    else:
        iterable = ()

    for code, value in iterable:
        if not isinstance(value, Mapping):
            continue
        if code not in PACKAGES:
            logger.warning("pricing.unknown_package_in_admin_settings", code=code)
            continue
        try:
            overrides.append(_parse_package_entry(code, value))
        except (InvalidPricingPayloadError, UnknownPackageError) as exc:
            logger.warning(
                "pricing.bad_package_override",
                code=code,
                error=str(exc),
            )

    try:
        global_discount = _coerce_percent(
            raw.get("global_discount", DEFAULT_GLOBAL_DISCOUNT),
            field_name="global_discount",
        )
    except InvalidPricingPayloadError as exc:
        logger.warning("pricing.bad_global_discount", error=str(exc))
        global_discount = DEFAULT_GLOBAL_DISCOUNT

    try:
        seasonal_promo = _coerce_percent(
            raw.get("seasonal_promo", DEFAULT_SEASONAL_PROMO),
            field_name="seasonal_promo",
        )
    except InvalidPricingPayloadError as exc:
        logger.warning("pricing.bad_seasonal_promo", error=str(exc))
        seasonal_promo = DEFAULT_SEASONAL_PROMO

    try:
        first_purchase_bonus = _coerce_percent(
            raw.get("first_purchase_bonus", DEFAULT_FIRST_PURCHASE_BONUS),
            field_name="first_purchase_bonus",
        )
    except InvalidPricingPayloadError as exc:
        logger.warning("pricing.bad_first_purchase_bonus", error=str(exc))
        first_purchase_bonus = DEFAULT_FIRST_PURCHASE_BONUS

    try:
        referral_bonus = _coerce_int(
            raw.get("referral_bonus", DEFAULT_REFERRAL_BONUS),
            field_name="referral_bonus",
            min_value=0,
            max_value=MAX_BONUS_TOKENS,
        )
    except InvalidPricingPayloadError as exc:
        logger.warning("pricing.bad_referral_bonus", error=str(exc))
        referral_bonus = DEFAULT_REFERRAL_BONUS

    try:
        daily_bonus = _coerce_int(
            raw.get("daily_bonus", DEFAULT_DAILY_BONUS),
            field_name="daily_bonus",
            min_value=0,
            max_value=MAX_BONUS_TOKENS,
        )
    except InvalidPricingPayloadError as exc:
        logger.warning("pricing.bad_daily_bonus", error=str(exc))
        daily_bonus = DEFAULT_DAILY_BONUS

    try:
        currency_rate = _coerce_currency_rate(raw.get("currency_rate"))
    except InvalidPricingPayloadError as exc:
        logger.warning("pricing.bad_currency_rate", error=str(exc))
        currency_rate = DEFAULT_CURRENCY_RATE

    return PricingConfig(
        packages=_merge_packages(overrides),
        global_discount=global_discount,
        seasonal_promo=seasonal_promo,
        first_purchase_bonus=first_purchase_bonus,
        referral_bonus=referral_bonus,
        daily_bonus=daily_bonus,
        currency_rate=currency_rate,
    )


def default_pricing_config() -> PricingConfig:
    """Return the in-code defaults — used on first read and as fallback."""
    return PricingConfig(
        packages=tuple(_default_override(p) for p in PACKAGES.values()),
    )


# ----------------------------------------------------------------- public API


# In-process TTL cache for the pricing config (issue #36).
#
# Every ``create_invoice`` call reads this row, and on a busy worker that
# turns into hundreds of identical SELECTs per second.  The config rarely
# changes (admin clicks "save" once a day at most) so a per-worker
# in-memory cache with a short TTL is the right shape: zero cross-pod
# coordination, microsecond reads, propagation delay bounded by the TTL.
#
# ``update_pricing_config`` calls :func:`invalidate_pricing_cache` to drop
# the entry on the worker that handled the admin request — other workers
# still see the change within :attr:`Settings.pricing_cache_ttl_seconds`
# (default 60s), which matches the acceptance criterion in issue #36.
_pricing_cache_lock = asyncio.Lock()
_pricing_cache: tuple[float, PricingConfig] | None = None


def _pricing_cache_ttl() -> float:
    return max(float(get_settings().pricing_cache_ttl_seconds), 0.0)


def invalidate_pricing_cache() -> None:
    """Drop the cached pricing config so the next read hits the DB."""
    global _pricing_cache
    _pricing_cache = None


async def _read_pricing_from_db(session: AsyncSession) -> PricingConfig:
    try:
        row = (
            await session.execute(
                select(AdminSetting).where(
                    AdminSetting.setting_key == PRICING_SETTING_KEY
                )
            )
        ).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 — never break callers on a config read
        logger.warning("pricing.config_load_failed", error=str(exc))
        return default_pricing_config()
    if row is None:
        return default_pricing_config()
    return _parse_pricing_value(row.setting_value)


async def load_pricing_config(session: AsyncSession) -> PricingConfig:
    """Read the current pricing config from ``admin_settings``.

    Tolerant of any DB-layer hiccup or schema drift — falls back to the
    in-code defaults so the payment flow can never be broken by a bad
    admin override.

    Backed by an in-process TTL cache (default 60s, see
    :attr:`Settings.pricing_cache_ttl_seconds`).  The cache is invalidated
    explicitly by :func:`update_pricing_config` on the worker that
    processed the change; cross-worker propagation is bounded by the TTL.
    Setting ``pricing_cache_ttl_seconds`` to ``0`` disables the cache —
    useful for the tests that exercise the parse paths directly.
    """
    global _pricing_cache
    ttl = _pricing_cache_ttl()
    now = monotonic()
    snapshot = _pricing_cache
    if ttl > 0 and snapshot is not None and snapshot[0] > now:
        return snapshot[1]

    async with _pricing_cache_lock:
        # Recheck under the lock so a thundering herd collapses into one DB
        # read; the second-pass snapshot reflects whichever coroutine got
        # here first.
        snapshot = _pricing_cache
        if ttl > 0 and snapshot is not None and snapshot[0] > monotonic():
            return snapshot[1]
        config = await _read_pricing_from_db(session)
        _pricing_cache = (monotonic() + ttl, config) if ttl > 0 else None
        return config


def effective_stars_for(
    package: PaymentPackage | PricingPackageOverride,
    config: PricingConfig,
) -> int:
    """Compute the discounted ``stars`` price for ``package``.

    The order of operations matches ``docs/PRICING_STRATEGY.md``: package
    override → global discount → seasonal promo → per-package discount.
    The result is clamped to at least 1 Star so Telegram Bot API never
    receives a 0-price invoice.
    """
    overrides = config.package_map()
    override = overrides.get(getattr(package, "code", ""))
    base = int(override.stars if override is not None else package.stars)
    pct = (
        int(config.global_discount)
        + int(config.seasonal_promo)
        + int(override.discount if override is not None else 0)
    )
    pct = max(0, min(pct, MAX_DISCOUNT_PERCENT))
    discounted = (base * (100 - pct)) // 100
    return max(MIN_STARS_PER_PACKAGE, discounted)


def effective_tokens_for(
    package: PaymentPackage | PricingPackageOverride,
    config: PricingConfig,
) -> int:
    """Return the tokens granted by ``package`` under the current config."""
    override = config.package_map().get(getattr(package, "code", ""))
    if override is not None:
        return int(override.tokens)
    return int(package.tokens)


def apply_pricing_to_package(
    package: PaymentPackage,
    config: PricingConfig,
) -> PaymentPackage:
    """Return a copy of ``package`` with the effective tokens + stars."""
    return replace(
        package,
        tokens=effective_tokens_for(package, config),
        stars=effective_stars_for(package, config),
    )


# ---------------------------------------------------------------- update flow


@dataclass(frozen=True)
class PricingUpdateRequest:
    packages: dict[str, dict[str, Any]] = field(default_factory=dict)
    global_discount: Any = None
    seasonal_promo: Any = None
    first_purchase_bonus: Any = None
    referral_bonus: Any = None
    daily_bonus: Any = None
    currency_rate: Any = None


def _parse_update_payload(
    payload: PricingUpdateRequest,
    current: PricingConfig,
) -> PricingConfig:
    """Validate ``payload`` against the current config; return the new one.

    Unspecified fields are inherited from ``current``.
    """
    overrides = {p.code: p for p in current.packages}
    for code, raw in payload.packages.items():
        if not isinstance(raw, Mapping):
            raise InvalidPricingPayloadError(
                f"packages[{code}] must be an object"
            )
        if code not in PACKAGES:
            raise UnknownPackageError(f"unknown package: {code!r}")
        overrides[code] = _parse_package_entry(code, raw)

    def _picked_percent(value: Any, fallback: int, name: str) -> int:
        if value is None:
            return fallback
        return _coerce_percent(value, field_name=name)

    def _picked_int(value: Any, fallback: int, name: str, *, max_value: int) -> int:
        if value is None:
            return fallback
        return _coerce_int(value, field_name=name, min_value=0, max_value=max_value)

    return PricingConfig(
        packages=_merge_packages(overrides.values()),
        global_discount=_picked_percent(
            payload.global_discount, current.global_discount, "global_discount"
        ),
        seasonal_promo=_picked_percent(
            payload.seasonal_promo, current.seasonal_promo, "seasonal_promo"
        ),
        first_purchase_bonus=_picked_percent(
            payload.first_purchase_bonus,
            current.first_purchase_bonus,
            "first_purchase_bonus",
        ),
        referral_bonus=_picked_int(
            payload.referral_bonus,
            current.referral_bonus,
            "referral_bonus",
            max_value=MAX_BONUS_TOKENS,
        ),
        daily_bonus=_picked_int(
            payload.daily_bonus,
            current.daily_bonus,
            "daily_bonus",
            max_value=MAX_BONUS_TOKENS,
        ),
        currency_rate=(
            current.currency_rate
            if payload.currency_rate is None
            else _coerce_currency_rate(payload.currency_rate)
        ),
    )


def _diff_config(before: PricingConfig, after: PricingConfig) -> dict[str, Any]:
    """Produce a JSON-safe diff of the two configs for the audit payload."""
    diff: dict[str, Any] = {}
    for field_name in (
        "global_discount",
        "seasonal_promo",
        "first_purchase_bonus",
        "referral_bonus",
        "daily_bonus",
        "currency_rate",
    ):
        old = getattr(before, field_name)
        new = getattr(after, field_name)
        if old != new:
            diff[field_name] = {"old": old, "new": new}

    pkg_diff: dict[str, Any] = {}
    before_pkgs = before.package_map()
    after_pkgs = after.package_map()
    for code in sorted(set(before_pkgs) | set(after_pkgs)):
        old_pkg = before_pkgs.get(code)
        new_pkg = after_pkgs.get(code)
        old_dict = old_pkg.to_dict() if old_pkg else None
        new_dict = new_pkg.to_dict() if new_pkg else None
        if old_dict != new_dict:
            pkg_diff[code] = {"old": old_dict, "new": new_dict}
    if pkg_diff:
        diff["packages"] = pkg_diff
    return diff


@dataclass(frozen=True)
class PricingUpdateResult:
    config: PricingConfig
    diff: dict[str, Any]
    audit_log_id: int


async def update_pricing_config(
    session: AsyncSession,
    *,
    admin: User,
    payload: PricingUpdateRequest,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> PricingUpdateResult:
    """Persist a new pricing config and append an audit-log row.

    Flushes the changes but does not commit — the API layer controls the
    outer transaction, mirroring the rest of the admin services.  Raises
    :class:`InvalidPricingPayloadError` on malformed input.
    """
    current = await load_pricing_config(session)
    new_config = _parse_update_payload(payload, current)
    diff = _diff_config(current, new_config)

    row = (
        await session.execute(
            select(AdminSetting).where(
                AdminSetting.setting_key == PRICING_SETTING_KEY
            )
        )
    ).scalar_one_or_none()

    serialized = new_config.to_dict()
    if row is None:
        row = AdminSetting(
            setting_key=PRICING_SETTING_KEY,
            setting_value=serialized,
            updated_by=admin.id,
        )
        session.add(row)
    else:
        row.setting_value = serialized
        row.updated_by = admin.id

    log = AdminAuditLog(
        admin_id=admin.id,
        target_user_id=None,
        action=PRICING_AUDIT_ACTION,
        payload={"diff": diff, "config": serialized},
        ip_address=(ip_address or "")[:64] or None,
        user_agent=(user_agent or "")[:512] or None,
    )
    session.add(log)
    await session.flush()

    # Drop the in-process cache so this worker serves the new config
    # immediately; other workers reconcile within the TTL.
    invalidate_pricing_cache()

    logger.info(
        "pricing.updated",
        admin_id=admin.id,
        diff_keys=sorted(diff.keys()),
        log_id=log.id,
    )
    return PricingUpdateResult(
        config=new_config,
        diff=diff,
        audit_log_id=int(log.id),
    )


__all__ = [
    "DEFAULT_CURRENCY_RATE",
    "DEFAULT_DAILY_BONUS",
    "DEFAULT_FIRST_PURCHASE_BONUS",
    "DEFAULT_GLOBAL_DISCOUNT",
    "DEFAULT_REFERRAL_BONUS",
    "DEFAULT_SEASONAL_PROMO",
    "InvalidPricingPayloadError",
    "MAX_BONUS_TOKENS",
    "MAX_DISCOUNT_PERCENT",
    "MAX_STARS_PER_PACKAGE",
    "MAX_TOKENS_PER_PACKAGE",
    "PRICING_AUDIT_ACTION",
    "PRICING_SETTING_KEY",
    "PaymentPackage",
    "PricingConfig",
    "PricingError",
    "PricingPackageOverride",
    "PricingUpdateRequest",
    "PricingUpdateResult",
    "UnknownPackageError",
    "apply_pricing_to_package",
    "default_pricing_config",
    "effective_stars_for",
    "effective_tokens_for",
    "invalidate_pricing_cache",
    "load_pricing_config",
    "update_pricing_config",
]
