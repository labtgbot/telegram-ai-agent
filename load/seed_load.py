"""Prepare the database for a load run against ``POST /generate/text``.

Two things make a sustained 100 RPS run feasible:

1. **Rate limits.** Production defaults cap ``text_per_day`` at 50 even
   for ``pro`` plans, which a 60-second load run blows through in well
   under a second. We push an ``admin_settings.rate_limits`` override
   with absurdly high quotas so the limiter never triggers.

2. **A user with a deep balance.** Each ``mode=basic`` call debits one
   token; at 100 RPS for 60 s that is ~6 000 tokens. Seed the load user
   with an order of magnitude more so the run never stalls on
   ``insufficient_tokens``.

The script is idempotent — running it twice updates rather than
duplicates rows.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Allow ``python load/seed_load.py`` from the repo root.
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.models import AdminSetting, User  # noqa: E402

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_ai_agent"
)

LOAD_USER_TELEGRAM_ID = int(os.environ.get("LOAD_USER_ID", "9000000001"))
LOAD_USER_USERNAME = os.environ.get("LOAD_USER_USERNAME", "loader")
LOAD_USER_FIRST_NAME = os.environ.get("LOAD_USER_FIRST_NAME", "Loader")
LOAD_USER_LANGUAGE = os.environ.get("LOAD_USER_LANGUAGE", "en")
LOAD_USER_TOKEN_BALANCE = int(os.environ.get("LOAD_USER_TOKEN_BALANCE", "10000000"))

# Quotas large enough that a 60 s run at 100 RPS (6 000 calls) never
# trips the limiter. Window=1 hour to match the existing schema.
HIGH_LIMITS = {
    "per_hour": {"limit": 10_000_000, "window_seconds": 3_600},
    "per_day": {"limit": 100_000_000, "window_seconds": 86_400},
    "image_per_day": {"limit": 100_000_000, "window_seconds": 86_400},
    "video_per_day": {"limit": 100_000_000, "window_seconds": 86_400},
    "voice_per_day": {"limit": 100_000_000, "window_seconds": 86_400},
    "text_per_day": {"limit": 100_000_000, "window_seconds": 86_400},
    "search_per_day": {"limit": 100_000_000, "window_seconds": 86_400},
    "document_per_day": {"limit": 100_000_000, "window_seconds": 86_400},
}

RATE_LIMIT_OVERRIDES = {
    "free": HIGH_LIMITS,
    "premium": HIGH_LIMITS,
    "pro": HIGH_LIMITS,
    "anonymous": {"per_hour": {"limit": 10_000_000, "window_seconds": 3_600}},
}


async def _upsert_load_user(session: AsyncSession) -> User:
    stmt = select(User).where(User.telegram_id == LOAD_USER_TELEGRAM_ID)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if user is None:
        user = User(
            telegram_id=LOAD_USER_TELEGRAM_ID,
            username=LOAD_USER_USERNAME,
            first_name=LOAD_USER_FIRST_NAME,
            language_code=LOAD_USER_LANGUAGE,
            token_balance=LOAD_USER_TOKEN_BALANCE,
            total_tokens_purchased=LOAD_USER_TOKEN_BALANCE,
            referral_code=f"LOAD-{LOAD_USER_TELEGRAM_ID}",
        )
        session.add(user)
        await session.flush()
        return user
    # Top up to keep idempotent re-runs from running out partway through.
    if user.token_balance < LOAD_USER_TOKEN_BALANCE:
        user.token_balance = LOAD_USER_TOKEN_BALANCE
    return user


async def _upsert_rate_limit_override(session: AsyncSession) -> None:
    stmt = select(AdminSetting).where(AdminSetting.setting_key == "rate_limits")
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is None:
        session.add(
            AdminSetting(setting_key="rate_limits", setting_value=RATE_LIMIT_OVERRIDES)
        )
    else:
        existing.setting_value = RATE_LIMIT_OVERRIDES


async def seed(database_url: str) -> None:
    engine = create_async_engine(database_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        user = await _upsert_load_user(session)
        await _upsert_rate_limit_override(session)
        await session.commit()
        print(
            f"Seeded load user telegram_id={user.telegram_id} "
            f"balance={user.token_balance:,}; rate-limit overrides installed."
        )
    await engine.dispose()


def main() -> None:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    asyncio.run(seed(database_url))


if __name__ == "__main__":
    main()
