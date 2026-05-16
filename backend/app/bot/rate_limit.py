"""Telegram bot helpers for rate-limit hits.

When a bot handler calls into :class:`app.services.rate_limiter.RateLimiter`
and gets a :class:`RateLimitedError`, it should call
:func:`format_rate_limit_message` to render a user-friendly Russian/English
message and :func:`upgrade_keyboard` to attach a CTA that points to the
Pro / Premium upgrade flow.

Keeping this logic next to the bot module (rather than in the service
layer) preserves the separation: the limiter knows about quotas, the bot
module knows about UX.
"""
from __future__ import annotations

from typing import Any

from app.services.rate_limit_config import (
    PLAN_ANONYMOUS,
    PLAN_FREE,
    PLAN_PREMIUM,
    PLAN_PRO,
)
from app.services.rate_limiter import RateLimitedError

# Codes from app.services.payment_packages.PACKAGES — see PRO_PLAN_CODE.
_PRO_PACKAGE = "pro_monthly"
_PREMIUM_PACKAGE = "premium"


def _format_wait(seconds: int) -> str:
    """Format ``seconds`` as a short, human-readable wait label."""
    seconds = max(1, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        minutes = seconds // 60
        return f"{minutes}m"
    hours = seconds // 3600
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    return f"{days}d"


def _quota_label(quota_key: str) -> str:
    """Map an internal quota key to a label used in the bot copy."""
    return {
        "per_hour": "hourly",
        "per_day": "daily",
        "image_per_day": "daily image",
        "video_per_day": "daily video",
        "voice_per_day": "daily voice",
    }.get(quota_key, quota_key)


def _next_plan(plan: str) -> str | None:
    """Suggest the next tier above ``plan``, or ``None`` for top-tier."""
    return {
        PLAN_ANONYMOUS: PLAN_FREE,
        PLAN_FREE: PLAN_PRO,
        PLAN_PREMIUM: PLAN_PRO,
    }.get(plan)


def _suggested_package(plan: str) -> str | None:
    """Pick the package code most likely to clear ``plan``'s limits."""
    if plan == PLAN_FREE:
        return _PRO_PACKAGE
    if plan == PLAN_PREMIUM:
        return _PRO_PACKAGE
    if plan == PLAN_ANONYMOUS:
        return None
    return None


def format_rate_limit_message(err: RateLimitedError) -> str:
    """Render the bot reply for a rate-limit hit.

    Mirrors the style of the existing handlers (HTML formatting, hint at
    the next action). Mentions the bucket name, the wait, and — for non-
    pro plans — a one-line upgrade hint.
    """
    wait = _format_wait(err.retry_after)
    quota = _quota_label(err.quota_key)

    if err.plan == PLAN_ANONYMOUS:
        body = (
            f"⏳ You've hit the {quota} limit for anonymous users.\n"
            f"Send /start to register and unlock the free tier."
        )
        return body

    body = (
        f"⏳ <b>{quota.capitalize()} limit reached</b>\n"
        f"Try again in <b>{wait}</b> "
        f"(plan: <b>{err.plan}</b>, limit: <b>{err.limit}</b>)."
    )

    upgrade = _next_plan(err.plan)
    if upgrade is not None:
        body += (
            "\n\n💎 Upgrade to "
            f"<b>{upgrade.capitalize()}</b> "
            "for higher limits — tap below or send /buy."
        )
    return body


def upgrade_keyboard(err: RateLimitedError) -> dict[str, Any] | None:
    """Return an inline-keyboard payload offering an upgrade.

    Returns ``None`` when no upgrade is meaningful (already on the top
    tier, or anonymous → user just needs to /start).
    """
    pkg = _suggested_package(err.plan)
    if pkg is None:
        return None
    next_plan = _next_plan(err.plan) or PLAN_PRO
    return {
        "inline_keyboard": [
            [
                {
                    "text": f"💎 Upgrade to {next_plan.capitalize()}",
                    "callback_data": f"buy:{pkg}",
                }
            ],
            [
                {"text": "🛒 See all packages", "callback_data": "menu:buy"},
            ],
        ]
    }


__all__ = [
    "format_rate_limit_message",
    "upgrade_keyboard",
]
