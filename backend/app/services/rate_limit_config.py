"""Rate-limit configuration: plan tiers + per-action quotas.

The data model is a two-level mapping ``{plan: {action: RateLimitRule}}``.
``action`` is one of:

* ``per_hour`` / ``per_day`` — apply to every billable request from the user;
* ``image_per_day`` / ``video_per_day`` / ``voice_per_day`` /
  ``text_per_day`` / ``search_per_day`` / ``document_per_day`` —
  specialised quotas for the heavier media / Phase 2 actions.

Plans are: ``anonymous`` (unauthenticated callers), ``free`` (registered
without a paid plan), ``premium`` (one-time premium grant), ``pro``
(active monthly subscription). See ``docs/architecture/adr/0004-rate-limiting.md``.

Defaults live in :data:`DEFAULT_RATE_LIMITS`. Operators can override any
plan/action pair via the ``rate_limits`` key in ``admin_settings`` —
:func:`load_rate_limits` reads that row and merges it on top of the
defaults so partial overrides keep the rest of the catalog working.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.admin_setting import AdminSetting

logger = get_logger(__name__)


ADMIN_SETTING_KEY: Final[str] = "rate_limits"

# Canonical plan codes used as keys throughout the limiter.
PLAN_ANONYMOUS: Final[str] = "anonymous"
PLAN_FREE: Final[str] = "free"
PLAN_PREMIUM: Final[str] = "premium"
PLAN_PRO: Final[str] = "pro"
KNOWN_PLANS: Final[frozenset[str]] = frozenset(
    {PLAN_ANONYMOUS, PLAN_FREE, PLAN_PREMIUM, PLAN_PRO}
)

# Canonical action codes. ``default`` is the catch-all bucket the dependency
# uses when the caller doesn't specify a specialised bucket.
ACTION_DEFAULT: Final[str] = "default"
ACTION_IMAGE: Final[str] = "image"
ACTION_VIDEO: Final[str] = "video"
ACTION_VOICE: Final[str] = "voice"
ACTION_TEXT: Final[str] = "text"
ACTION_SEARCH: Final[str] = "search"
ACTION_DOCUMENT: Final[str] = "document"
KNOWN_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        ACTION_DEFAULT,
        ACTION_IMAGE,
        ACTION_VIDEO,
        ACTION_VOICE,
        ACTION_TEXT,
        ACTION_SEARCH,
        ACTION_DOCUMENT,
    }
)


@dataclass(frozen=True)
class RateLimitRule:
    """One sliding-window quota: ``limit`` events per ``window_seconds``."""

    limit: int
    window_seconds: int

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("rate-limit `limit` must be > 0")
        if self.window_seconds <= 0:
            raise ValueError("rate-limit `window_seconds` must be > 0")


# Quota keys exposed in admin settings. They map to one ``RateLimitRule`` each
# and have stable semantics so admins can change limits without code changes.
_HOUR_SECONDS: Final[int] = 3600
_DAY_SECONDS: Final[int] = 24 * 3600


def _hour(limit: int) -> RateLimitRule:
    return RateLimitRule(limit=limit, window_seconds=_HOUR_SECONDS)


def _day(limit: int) -> RateLimitRule:
    return RateLimitRule(limit=limit, window_seconds=_DAY_SECONDS)


# Default catalog. The values match the SECURITY.md / ADR-0004 reference table
# and provide sensible quotas for the heavier media actions.
DEFAULT_RATE_LIMITS: Final[dict[str, dict[str, RateLimitRule]]] = {
    PLAN_ANONYMOUS: {
        "per_hour": _hour(5),
    },
    PLAN_FREE: {
        "per_hour": _hour(10),
        "per_day": _day(100),
        "image_per_day": _day(5),
        "video_per_day": _day(2),
        "voice_per_day": _day(10),
        "text_per_day": _day(50),
        "search_per_day": _day(30),
        "document_per_day": _day(3),
    },
    PLAN_PREMIUM: {
        "per_hour": _hour(100),
        "per_day": _day(1_000),
        "image_per_day": _day(50),
        "video_per_day": _day(20),
        "voice_per_day": _day(100),
        "text_per_day": _day(500),
        "search_per_day": _day(300),
        "document_per_day": _day(30),
    },
    PLAN_PRO: {
        "per_hour": _hour(500),
        "per_day": _day(5_000),
        "image_per_day": _day(200),
        "video_per_day": _day(100),
        "voice_per_day": _day(500),
        "text_per_day": _day(2_000),
        "search_per_day": _day(1_500),
        "document_per_day": _day(150),
    },
}


# Which quota keys apply to a given action. ``default`` is always covered by
# the universal counters; media + text actions additionally consume their
# dedicated daily bucket.
ACTION_QUOTA_KEYS: Final[dict[str, tuple[str, ...]]] = {
    ACTION_DEFAULT: ("per_hour", "per_day"),
    ACTION_IMAGE: ("per_hour", "per_day", "image_per_day"),
    ACTION_VIDEO: ("per_hour", "per_day", "video_per_day"),
    ACTION_VOICE: ("per_hour", "per_day", "voice_per_day"),
    ACTION_TEXT: ("per_hour", "per_day", "text_per_day"),
    ACTION_SEARCH: ("per_hour", "per_day", "search_per_day"),
    ACTION_DOCUMENT: ("per_hour", "per_day", "document_per_day"),
}


@dataclass(frozen=True)
class RateLimitConfig:
    """Snapshot of the active per-plan quotas."""

    plans: dict[str, dict[str, RateLimitRule]] = field(default_factory=dict)

    def rules_for(self, plan: str, action: str) -> list[tuple[str, RateLimitRule]]:
        """Return ``(quota_key, rule)`` pairs to enforce for ``(plan, action)``.

        The list preserves the order from :data:`ACTION_QUOTA_KEYS` so the
        most aggressive (hourly) bucket is checked first. Quotas not defined
        for the plan are silently skipped — this lets admins disable specific
        buckets (e.g. drop ``per_day`` from anonymous) by removing the key.
        """
        plan_rules = self.plans.get(plan) or {}
        out: list[tuple[str, RateLimitRule]] = []
        for key in ACTION_QUOTA_KEYS.get(action, ACTION_QUOTA_KEYS[ACTION_DEFAULT]):
            rule = plan_rules.get(key)
            if rule is not None:
                out.append((key, rule))
        return out


def _coerce_rule(value: object) -> RateLimitRule | None:
    """Build a :class:`RateLimitRule` from the JSONB payload.

    Accepts ``{"limit": int, "window_seconds": int}`` plus a couple of
    shorthand forms (``int`` → per-hour, ``{"per_hour": int}`` etc.) so the
    DB-stored config can stay terse. Returns ``None`` for unrecognised
    shapes, which lets the caller fall back to the default.
    """
    if isinstance(value, RateLimitRule):
        return value
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return _hour(value)
    if not isinstance(value, dict):
        return None
    limit_raw = value.get("limit")
    window_raw = value.get("window_seconds") or value.get("window")
    if window_raw is None:
        # Shorthand: {"per_hour": 10} or {"per_day": 100}
        for k, sec in (("per_hour", _HOUR_SECONDS), ("per_day", _DAY_SECONDS)):
            if isinstance(value.get(k), int) and not isinstance(value.get(k), bool):
                limit_raw = value[k]
                window_raw = sec
                break
    try:
        limit = int(limit_raw)  # type: ignore[arg-type]
        window = int(window_raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if limit <= 0 or window <= 0:
        return None
    return RateLimitRule(limit=limit, window_seconds=window)


def merge_overrides(
    base: Mapping[str, Mapping[str, RateLimitRule]],
    overrides: Mapping[str, object] | None,
) -> dict[str, dict[str, RateLimitRule]]:
    """Layer ``overrides`` over ``base`` and return the merged catalog.

    ``overrides`` is shaped like the admin settings payload — a mapping of
    plan → action → rule (or shorthand). Unknown plans / actions are kept so
    new buckets can be added through the CRM without redeploying.
    """
    merged: dict[str, dict[str, RateLimitRule]] = {
        plan: dict(rules) for plan, rules in base.items()
    }
    if not overrides:
        return merged
    if not isinstance(overrides, Mapping):
        logger.warning("rate_limits.overrides_not_mapping", got=type(overrides).__name__)
        return merged

    for plan, plan_overrides in overrides.items():
        plan_key = str(plan)
        if not isinstance(plan_overrides, Mapping):
            logger.warning(
                "rate_limits.plan_overrides_not_mapping",
                plan=plan_key,
                got=type(plan_overrides).__name__,
            )
            continue
        bucket = merged.setdefault(plan_key, {})
        for action, raw in plan_overrides.items():
            rule = _coerce_rule(raw)
            if rule is None:
                logger.warning(
                    "rate_limits.bad_override",
                    plan=plan_key,
                    action=str(action),
                    raw=raw,
                )
                continue
            bucket[str(action)] = rule
    return merged


async def load_rate_limits(session: AsyncSession) -> RateLimitConfig:
    """Load the active rate-limit catalog, merging admin overrides on top.

    Falls back to :data:`DEFAULT_RATE_LIMITS` if the admin row is missing or
    malformed, so a freshly-migrated database is operational without manual
    seeding. Errors are logged, not raised.
    """
    overrides: Mapping[str, object] | None = None
    try:
        stmt = select(AdminSetting.setting_value).where(
            AdminSetting.setting_key == ADMIN_SETTING_KEY
        )
        result = (await session.execute(stmt)).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 — never break callers on a config read
        logger.warning("rate_limits.load_failed", error=str(exc))
        result = None
    if isinstance(result, Mapping):
        overrides = result
    elif result is not None:
        logger.warning(
            "rate_limits.bad_setting_value",
            got=type(result).__name__,
        )
    plans = merge_overrides(DEFAULT_RATE_LIMITS, overrides)
    return RateLimitConfig(plans=plans)


__all__ = [
    "ACTION_DEFAULT",
    "ACTION_DOCUMENT",
    "ACTION_IMAGE",
    "ACTION_QUOTA_KEYS",
    "ACTION_SEARCH",
    "ACTION_TEXT",
    "ACTION_VIDEO",
    "ACTION_VOICE",
    "ADMIN_SETTING_KEY",
    "DEFAULT_RATE_LIMITS",
    "KNOWN_ACTIONS",
    "KNOWN_PLANS",
    "PLAN_ANONYMOUS",
    "PLAN_FREE",
    "PLAN_PREMIUM",
    "PLAN_PRO",
    "RateLimitConfig",
    "RateLimitRule",
    "load_rate_limits",
    "merge_overrides",
]
