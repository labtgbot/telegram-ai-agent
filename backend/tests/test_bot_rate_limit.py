"""Unit tests for the bot rate-limit message helper."""
from __future__ import annotations

from app.bot.rate_limit import format_rate_limit_message, upgrade_keyboard
from app.services.rate_limit_config import (
    PLAN_ANONYMOUS,
    PLAN_FREE,
    PLAN_PREMIUM,
    PLAN_PRO,
)
from app.services.rate_limiter import RateLimitedError


def _err(
    *,
    plan: str = PLAN_FREE,
    quota: str = "per_hour",
    limit: int = 10,
    retry_after: int = 60,
) -> RateLimitedError:
    return RateLimitedError(
        plan=plan,
        action="default",
        quota_key=quota,
        limit=limit,
        retry_after=retry_after,
        reset_after=retry_after,
    )


def test_format_message_for_free_user_mentions_upgrade_to_pro() -> None:
    msg = format_rate_limit_message(_err())
    assert "limit" in msg.lower()
    assert "free" in msg.lower()
    assert "pro" in msg.lower()


def test_format_message_for_premium_user_suggests_pro() -> None:
    msg = format_rate_limit_message(_err(plan=PLAN_PREMIUM))
    assert "pro" in msg.lower()


def test_format_message_for_pro_does_not_suggest_upgrade() -> None:
    msg = format_rate_limit_message(_err(plan=PLAN_PRO))
    assert "upgrade" not in msg.lower()


def test_format_message_for_anonymous_mentions_start() -> None:
    msg = format_rate_limit_message(_err(plan=PLAN_ANONYMOUS))
    assert "/start" in msg


def test_format_message_includes_retry_window() -> None:
    msg = format_rate_limit_message(_err(retry_after=120))
    assert "2m" in msg  # 120 seconds → 2 minutes


def test_format_message_handles_hour_window() -> None:
    msg = format_rate_limit_message(_err(retry_after=7200))
    assert "2h" in msg


def test_format_message_quota_label_is_human_readable() -> None:
    msg = format_rate_limit_message(_err(quota="image_per_day"))
    assert "daily image" in msg.lower()


# ----------------------------------------------------------------- keyboard


def test_upgrade_keyboard_for_free_offers_pro_package() -> None:
    kb = upgrade_keyboard(_err(plan=PLAN_FREE))
    assert kb is not None
    rows = kb["inline_keyboard"]
    assert any(
        btn.get("callback_data") == "buy:pro_monthly"
        for row in rows
        for btn in row
    )


def test_upgrade_keyboard_for_premium_offers_pro_package() -> None:
    kb = upgrade_keyboard(_err(plan=PLAN_PREMIUM))
    assert kb is not None


def test_upgrade_keyboard_for_pro_returns_none() -> None:
    assert upgrade_keyboard(_err(plan=PLAN_PRO)) is None


def test_upgrade_keyboard_for_anonymous_returns_none() -> None:
    assert upgrade_keyboard(_err(plan=PLAN_ANONYMOUS)) is None
