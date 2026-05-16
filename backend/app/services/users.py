"""User-centric service functions used by auth endpoints.

Keeping these out of the API layer makes them straightforward to unit-test
without spinning up a FastAPI app.
"""
from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.rbac import Role
from app.models.user import User

REFERRAL_CODE_LENGTH = 8
# RFC 4648 base32 alphabet — uppercase letters and digits 2-7. Avoids
# ambiguous glyphs (0/O, 1/I/L) which matters when users dictate codes
# verbally or read them off a screen.
_REFERRAL_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"


def generate_referral_code() -> str:
    """Return a URL-safe 8-character base32 referral code."""
    return "".join(secrets.choice(_REFERRAL_ALPHABET) for _ in range(REFERRAL_CODE_LENGTH))


async def find_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def find_user_by_telegram_id(
    session: AsyncSession, telegram_id: int
) -> User | None:
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()


def _normalize(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def upsert_telegram_user(
    session: AsyncSession,
    *,
    telegram_user: dict[str, Any],
    super_admin_ids: set[int] | None = None,
) -> tuple[User, bool]:
    """Find-or-create a user from a Telegram ``user`` dict.

    Returns ``(user, created)``.  On first contact a referral code is
    generated and any conflict on the unique index is retried with a fresh
    code.  Existing users have their profile fields refreshed.
    """
    try:
        telegram_id = int(telegram_user["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("telegram_user.id missing or not an integer") from exc

    user = await find_user_by_telegram_id(session, telegram_id)
    now = datetime.now(UTC)
    super_ids = super_admin_ids or set()

    if user is None:
        for _ in range(5):
            code = generate_referral_code()
            existing = await session.execute(
                select(User.id).where(User.referral_code == code)
            )
            if existing.scalar_one_or_none() is None:
                break
        else:
            code = generate_referral_code()

        role = (
            Role.SUPER_ADMIN.value
            if telegram_id in super_ids
            else Role.USER.value
        )
        user = User(
            telegram_id=telegram_id,
            username=_normalize(telegram_user.get("username")),
            first_name=_normalize(telegram_user.get("first_name")),
            last_name=_normalize(telegram_user.get("last_name")),
            language_code=_normalize(telegram_user.get("language_code")) or "ru",
            referral_code=code,
            role=role,
            last_active_at=now,
        )
        session.add(user)
        await session.flush()
        return user, True

    user.username = _normalize(telegram_user.get("username")) or user.username
    user.first_name = _normalize(telegram_user.get("first_name")) or user.first_name
    user.last_name = _normalize(telegram_user.get("last_name")) or user.last_name
    user.language_code = (
        _normalize(telegram_user.get("language_code")) or user.language_code
    )
    user.last_active_at = now
    if (
        telegram_id in super_ids
        and Role.coerce(user.role) is Role.USER
    ):
        user.role = Role.SUPER_ADMIN.value
    await session.flush()
    return user, False


async def record_admin_login(session: AsyncSession, user: User) -> None:
    user.last_login_at = datetime.now(UTC)
    await session.flush()
