"""User registration for the Telegram Bot side.

Wraps :func:`app.services.users.upsert_telegram_user` with bot-specific
side effects:

* Credit a signup bonus on first contact (recorded as a ``bonus``
  transaction so analytics has an audit trail).
* Link the new user to the inviter when ``/start`` carries a referral
  payload (``/start REF123``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.transaction import Transaction
from app.models.user import User
from app.services.users import upsert_telegram_user

logger = get_logger(__name__)


@dataclass
class RegistrationResult:
    """Returned by :func:`register_or_update_user`."""

    user: User
    created: bool
    bonus_credited: int
    referrer: User | None = None


def _normalize_referral_code(payload: str | None) -> str | None:
    if not payload:
        return None
    token = payload.strip()
    if not token:
        return None
    return token[:50]


async def _find_user_by_referral_code(
    session: AsyncSession, code: str
) -> User | None:
    result = await session.execute(select(User).where(User.referral_code == code))
    return result.scalar_one_or_none()


async def register_or_update_user(
    session: AsyncSession,
    *,
    telegram_user: dict[str, Any],
    referral_payload: str | None = None,
    signup_bonus_tokens: int = 50,
    super_admin_ids: set[int] | None = None,
) -> RegistrationResult:
    """Create-or-update the user and credit the signup bonus on first contact.

    ``referral_payload`` is taken from ``/start <payload>`` arguments and is
    only consulted on the very first registration of a given Telegram ID —
    we never reassign ``referred_by`` later.
    """
    user, created = await upsert_telegram_user(
        session,
        telegram_user=telegram_user,
        super_admin_ids=super_admin_ids,
    )

    if not created:
        return RegistrationResult(user=user, created=False, bonus_credited=0)

    referrer: User | None = None
    referral_code = _normalize_referral_code(referral_payload)
    if referral_code and referral_code != user.referral_code:
        referrer = await _find_user_by_referral_code(session, referral_code)
        if referrer and referrer.id != user.id and not referrer.is_banned:
            user.referred_by = referrer.id
            await session.flush()
        elif referrer is None:
            logger.info("bot.register.unknown_referral_code", code=referral_code)

    bonus = max(int(signup_bonus_tokens), 0)
    if bonus:
        user.token_balance = (user.token_balance or 0) + bonus
        session.add(
            Transaction(
                user_id=user.id,
                transaction_type="bonus",
                tokens_amount=bonus,
                package_name="signup_bonus",
                payment_status="completed",
                completed_at=datetime.now(UTC),
            )
        )
        await session.flush()

    logger.info(
        "bot.user_registered",
        telegram_id=user.telegram_id,
        user_id=user.id,
        bonus=bonus,
        referrer_id=referrer.id if referrer else None,
    )
    return RegistrationResult(
        user=user,
        created=True,
        bonus_credited=bonus,
        referrer=referrer,
    )
