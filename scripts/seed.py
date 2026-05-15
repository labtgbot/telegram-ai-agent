"""Seed development data.

Запуск (из корня репозитория, после ``alembic upgrade head``):

    DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_ai_agent \
        python -m scripts.seed

Скрипт идемпотентен: повторный запуск ничего не дублирует — он берёт
существующие записи по уникальным ключам и обновляет балансы.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Allow ``python scripts/seed.py`` from the repo root.
ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import (  # noqa: E402
    AdminSetting,
    DailyAnalytics,
    Subscription,
    TokenUsageLog,
    Transaction,
    User,
)

DEFAULT_DATABASE_URL = (
    "postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_ai_agent"
)


async def _upsert_user(session: AsyncSession, **fields) -> User:
    stmt = select(User).where(User.telegram_id == fields["telegram_id"])
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        return existing
    user = User(**fields)
    session.add(user)
    await session.flush()
    return user


async def _upsert_setting(session: AsyncSession, key: str, value: dict) -> AdminSetting:
    stmt = select(AdminSetting).where(AdminSetting.setting_key == key)
    existing = (await session.execute(stmt)).scalar_one_or_none()
    if existing is not None:
        existing.setting_value = value
        return existing
    setting = AdminSetting(setting_key=key, setting_value=value)
    session.add(setting)
    return setting


async def seed(database_url: str) -> None:
    engine = create_async_engine(database_url, future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async with factory() as session:
        # Users
        alice = await _upsert_user(
            session,
            telegram_id=1001,
            username="alice",
            first_name="Alice",
            last_name="Dev",
            language_code="en",
            token_balance=1200,
            total_tokens_purchased=1200,
            referral_code="ALICE-DEV",
        )
        bob = await _upsert_user(
            session,
            telegram_id=1002,
            username="bob",
            first_name="Bob",
            language_code="ru",
            token_balance=300,
            total_tokens_purchased=500,
            total_tokens_spent=200,
            referral_code="BOB-DEV",
            referred_by=alice.id,
        )
        carol = await _upsert_user(
            session,
            telegram_id=1003,
            username="carol",
            first_name="Carol",
            language_code="ru",
            is_premium=True,
            premium_expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            token_balance=2000,
            total_tokens_purchased=2000,
            referral_code="CAROL-DEV",
        )

        # Transactions for Bob (purchase + spend) — keyed by payment_id for idempotency.
        existing_payment_ids = {
            row
            for row in (
                await session.execute(
                    select(Transaction.payment_id).where(Transaction.user_id == bob.id)
                )
            ).scalars()
        }
        if "seed-payment-001" not in existing_payment_ids:
            session.add_all(
                [
                    Transaction(
                        user_id=bob.id,
                        transaction_type="purchase",
                        tokens_amount=500,
                        stars_amount=250,
                        usd_amount=Decimal("4.99"),
                        package_name="Starter",
                        payment_id="seed-payment-001",
                        payment_status="completed",
                        payment_method="telegram_stars",
                        completed_at=datetime.now(timezone.utc),
                    ),
                    Transaction(
                        user_id=bob.id,
                        transaction_type="spend",
                        tokens_amount=-200,
                        payment_id="seed-spend-001",
                        payment_status="completed",
                        completed_at=datetime.now(timezone.utc),
                    ),
                ]
            )

        # One usage log to exercise the partitioned table.
        existing_logs = (
            await session.execute(
                select(TokenUsageLog.id).where(TokenUsageLog.user_id == bob.id)
            )
        ).first()
        if existing_logs is None:
            session.add(
                TokenUsageLog(
                    user_id=bob.id,
                    service_type="text_chat",
                    tokens_consumed=200,
                    request_params={"model": "claude-sonnet", "prompt_tokens": 150},
                    response_status="ok",
                    processing_time_ms=842,
                    composio_tool="anthropic.chat",
                    mcp_server="anthropic",
                )
            )

        # Admin settings (token prices and feature flags)
        await _upsert_setting(
            session,
            "token_packages",
            {
                "starter": {"tokens": 500, "stars": 250},
                "basic": {"tokens": 1200, "stars": 500},
                "premium": {"tokens": 2000, "stars": 750},
            },
        )
        await _upsert_setting(
            session,
            "feature_flags",
            {"image_generation": True, "video_generation": False},
        )

        # Daily analytics snapshot (today)
        today = date.today()
        stmt = select(DailyAnalytics).where(DailyAnalytics.date == today)
        if (await session.execute(stmt)).scalar_one_or_none() is None:
            session.add(
                DailyAnalytics(
                    date=today,
                    total_users=3,
                    new_users=3,
                    active_users=2,
                    premium_users=1,
                    total_tokens_sold=3700,
                    total_stars_revenue=1500,
                    total_usd_revenue=Decimal("19.97"),
                    total_requests=12,
                    image_generations=3,
                    video_generations=0,
                    text_queries=9,
                    avg_tokens_per_user=Decimal("1233.33"),
                    conversion_rate=Decimal("0.33"),
                )
            )

        # Subscription for Carol
        stmt = select(Subscription).where(Subscription.user_id == carol.id)
        if (await session.execute(stmt)).scalar_one_or_none() is None:
            now = datetime.now(timezone.utc)
            session.add(
                Subscription(
                    user_id=carol.id,
                    plan_code="pro_monthly",
                    starts_at=now,
                    expires_at=now + timedelta(days=30),
                    auto_renew=True,
                    status="active",
                )
            )

        await session.commit()
    await engine.dispose()


def main() -> None:
    database_url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    asyncio.run(seed(database_url))
    print(f"Seed completed for {database_url}")


if __name__ == "__main__":
    main()
