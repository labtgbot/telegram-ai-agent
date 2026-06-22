"""Integration tests that need a real PostgreSQL.

Skipped automatically when no ``DATABASE_URL`` is configured (see conftest).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models import (
    AdminSetting,
    Broadcast,
    BroadcastRecipient,
    ChatMessage,
    ChatThread,
    DailyAnalytics,
    Subscription,
    TokenUsageLog,
    Transaction,
    User,
)


@pytest.mark.asyncio
async def test_insert_and_query_user(db_session):
    user = User(
        telegram_id=999001,
        username="testuser",
        first_name="Test",
        referral_code="TEST-DB-001",
    )
    db_session.add(user)
    await db_session.flush()
    assert user.id is not None

    result = await db_session.execute(select(User).where(User.telegram_id == 999001))
    fetched = result.scalar_one()
    assert fetched.username == "testuser"
    assert fetched.token_balance == 0
    assert fetched.is_premium is False
    assert fetched.created_at is not None


@pytest.mark.asyncio
async def test_unique_telegram_id(db_session):
    db_session.add(
        User(telegram_id=999002, referral_code="TEST-DB-002")
    )
    await db_session.flush()
    db_session.add(
        User(telegram_id=999002, referral_code="TEST-DB-002B")
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_transaction_check_constraint_rejects_invalid_type(db_session):
    user = User(telegram_id=999003, referral_code="TEST-DB-003")
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        Transaction(
            user_id=user.id,
            transaction_type="invalid-type",
            tokens_amount=100,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_transaction_allowed_types(db_session):
    user = User(telegram_id=999004, referral_code="TEST-DB-004")
    db_session.add(user)
    await db_session.flush()

    for tx_type in ("purchase", "spend", "bonus", "refund", "manual_bonus"):
        db_session.add(
            Transaction(
                user_id=user.id,
                transaction_type=tx_type,
                tokens_amount=10,
                usd_amount=Decimal("0.99"),
            )
        )
    await db_session.flush()


@pytest.mark.asyncio
async def test_broadcast_status_check_constraint_rejects_invalid_value(db_session):
    user = User(telegram_id=999020, referral_code="TEST-DB-020")
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        Broadcast(
            created_by=user.id,
            text="hello",
            audience="all",
            status="invalid-status",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_broadcast_audience_check_constraint_rejects_invalid_value(db_session):
    user = User(telegram_id=999021, referral_code="TEST-DB-021")
    db_session.add(user)
    await db_session.flush()

    db_session.add(
        Broadcast(
            created_by=user.id,
            text="hello",
            audience="invalid-audience",
            status="draft",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_broadcast_recipient_status_check_constraint_rejects_invalid_value(db_session):
    user = User(telegram_id=999022, referral_code="TEST-DB-022")
    db_session.add(user)
    await db_session.flush()

    broadcast = Broadcast(
        created_by=user.id,
        text="hello",
        audience="all",
        status="draft",
    )
    db_session.add(broadcast)
    await db_session.flush()

    db_session.add(
        BroadcastRecipient(
            broadcast_id=broadcast.id,
            user_id=user.id,
            telegram_id=user.telegram_id,
            status="invalid-status",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_chat_message_user_id_must_match_thread_owner(db_session):
    owner = User(telegram_id=999009, referral_code="TEST-DB-009")
    other = User(telegram_id=999010, referral_code="TEST-DB-010")
    db_session.add_all([owner, other])
    await db_session.flush()

    thread = ChatThread(user_id=owner.id, external_id="owner-thread")
    db_session.add(thread)
    await db_session.flush()

    db_session.add(
        ChatMessage(
            thread_id=thread.id,
            user_id=other.id,
            role="user",
            content="wrong owner",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()


@pytest.mark.asyncio
async def test_token_usage_log_inserts_into_partition(db_session):
    user = User(telegram_id=999005, referral_code="TEST-DB-005")
    db_session.add(user)
    await db_session.flush()

    log = TokenUsageLog(
        user_id=user.id,
        service_type="text_chat",
        tokens_consumed=42,
        request_params={"prompt": "hi", "model": "claude"},
        response_status="ok",
        processing_time_ms=150,
        composio_tool="anthropic.chat",
        mcp_server="anthropic",
    )
    db_session.add(log)
    await db_session.flush()
    assert log.id is not None

    # The parent table must report the row, and a monthly partition must exist.
    res = await db_session.execute(
        text("SELECT count(*) FROM token_usage_logs WHERE user_id = :uid"),
        {"uid": user.id},
    )
    assert res.scalar_one() == 1

    res = await db_session.execute(
        text(
            "SELECT count(*) FROM pg_inherits "
            "WHERE inhparent = 'token_usage_logs'::regclass"
        )
    )
    assert res.scalar_one() >= 1


@pytest.mark.asyncio
async def test_token_usage_log_future_insert_uses_default_partition(db_session):
    user = User(telegram_id=999007, referral_code="TEST-DB-007")
    db_session.add(user)
    await db_session.flush()

    future_created_at = datetime.now(UTC) + timedelta(days=400)
    log = TokenUsageLog(
        user_id=user.id,
        service_type="text_chat",
        tokens_consumed=7,
        created_at=future_created_at,
        response_status="ok",
    )
    db_session.add(log)
    await db_session.flush()
    assert log.id is not None

    res = await db_session.execute(
        text(
            """
            SELECT tableoid::regclass::text
            FROM token_usage_logs
            WHERE id = :id AND created_at = :created_at
            """
        ),
        {"id": log.id, "created_at": future_created_at},
    )
    assert res.scalar_one() == "token_usage_logs_default"


@pytest.mark.asyncio
async def test_token_usage_partition_maintenance_rehomes_default_rows(db_session):
    from app.services.token_usage_partitions import ensure_token_usage_partitions

    user = User(telegram_id=999008, referral_code="TEST-DB-008")
    db_session.add(user)
    await db_session.flush()

    future_created_at = datetime.now(UTC) + timedelta(days=430)
    log = TokenUsageLog(
        user_id=user.id,
        service_type="image_generation",
        tokens_consumed=9,
        created_at=future_created_at,
        response_status="ok",
    )
    db_session.add(log)
    await db_session.flush()

    result = await ensure_token_usage_partitions(
        db_session,
        reference_date=future_created_at,
        months_ahead=0,
    )

    expected_partition = f"token_usage_logs_{future_created_at.strftime('%Y_%m')}"
    assert result.default_created is False
    assert result.partitions_created == (expected_partition,)
    assert result.rows_moved == 1

    res = await db_session.execute(
        text(
            """
            SELECT tableoid::regclass::text
            FROM token_usage_logs
            WHERE id = :id AND created_at = :created_at
            """
        ),
        {"id": log.id, "created_at": future_created_at},
    )
    assert res.scalar_one() == expected_partition


@pytest.mark.asyncio
async def test_partitioning_partition_by_clause(db_session):
    res = await db_session.execute(
        text(
            "SELECT pg_get_partkeydef('token_usage_logs'::regclass) AS def"
        )
    )
    partkey = res.scalar_one()
    assert partkey is not None
    assert "RANGE" in partkey.upper()
    assert "created_at" in partkey


@pytest.mark.asyncio
async def test_admin_setting_jsonb_round_trip(db_session):
    payload = {"prices": {"starter": 250}, "flags": ["images", "voice"]}
    setting = AdminSetting(setting_key="test-key", setting_value=payload)
    db_session.add(setting)
    await db_session.flush()

    fetched = (
        await db_session.execute(
            select(AdminSetting).where(AdminSetting.setting_key == "test-key")
        )
    ).scalar_one()
    assert fetched.setting_value == payload


@pytest.mark.asyncio
async def test_admin_setting_updated_by_is_cleared_when_user_is_deleted(db_session):
    user = User(telegram_id=999007, referral_code="TEST-DB-007")
    db_session.add(user)
    await db_session.flush()

    setting = AdminSetting(
        setting_key="user-owned-setting",
        setting_value={"enabled": True},
        updated_by=user.id,
    )
    db_session.add(setting)
    await db_session.flush()

    await db_session.delete(user)
    await db_session.flush()
    await db_session.refresh(setting)

    assert setting.updated_by is None


@pytest.mark.asyncio
async def test_daily_analytics_defaults(db_session):
    today = datetime.now(UTC).date()
    row = DailyAnalytics(date=today)
    db_session.add(row)
    await db_session.flush()
    await db_session.refresh(row)
    assert row.total_users == 0
    assert row.total_usd_revenue == Decimal("0.00")


@pytest.mark.asyncio
async def test_subscription_links_to_user(db_session):
    user = User(telegram_id=999006, referral_code="TEST-DB-006")
    db_session.add(user)
    await db_session.flush()

    now = datetime.now(UTC)
    sub = Subscription(
        user_id=user.id,
        plan_code="pro_monthly",
        starts_at=now,
        expires_at=now + timedelta(days=30),
    )
    db_session.add(sub)
    await db_session.flush()
    assert sub.id is not None
    assert sub.auto_renew is True
    assert sub.status == "active"


@pytest.mark.asyncio
async def test_partial_index_on_premium_users(db_session):
    res = await db_session.execute(
        text(
            """
            SELECT pg_get_indexdef(indexrelid) AS def
            FROM pg_index
            JOIN pg_class ON pg_class.oid = pg_index.indexrelid
            WHERE pg_class.relname = 'ix_users_premium'
            """
        )
    )
    definition = res.scalar_one()
    assert "WHERE" in definition.upper()
    assert "is_premium" in definition
