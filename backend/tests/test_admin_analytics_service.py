"""Tests for the admin analytics service (Phase 3, issue #27).

Layered tests:

1. Pure helpers — range normalisation, group-by coercion, funnel math.
   No DB, no FastAPI.
2. DB-backed flow — revenue aggregation, funnel + retention,
   LTV per cohort, token usage, and the daily snapshot upsert.
   Skipped without ``DATABASE_URL``.

The DB tests insert minimal users and transactions then assert the
shape of the response.  They intentionally avoid mocking SQLAlchemy
because the value of these tests is verifying the SQL actually returns
the right rows on Postgres (we use partial indexes and date_trunc that
SQLite cannot emulate).
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

# Pre-warm ``app.bot`` so ``app.bot.__init__`` finishes loading before
# the analytics service drags in the wider models graph — same workaround
# used by ``tests/test_pricing_service.py``.
from app.bot.client import TelegramApiError  # noqa: F401
from app.models.daily_analytics import DailyAnalytics
from app.models.token_usage_log import TokenUsageLog
from app.models.transaction import Transaction
from app.models.user import User
from app.services.analytics import (
    DEFAULT_RETENTION_WEEKS,
    FUNNEL_STAGES,
    FunnelStage,
    InvalidRangeError,
    UnsupportedGroupingError,
    _build_funnel,
    _coerce_group,
    _normalise_range,
    aggregate_daily_snapshot,
    get_ltv_summary,
    get_revenue_summary,
    get_token_usage,
    get_user_behavior,
    revenue_csv,
)

# =========================================================================
# Pure helpers — no DB.
# =========================================================================


def test_coerce_group_accepts_known_values() -> None:
    assert _coerce_group("day") == "day"
    assert _coerce_group("WEEK") == "week"
    assert _coerce_group("Month") == "month"
    assert _coerce_group(None) == "day"


def test_coerce_group_rejects_unknown_value() -> None:
    with pytest.raises(UnsupportedGroupingError):
        _coerce_group("year")


def test_normalise_range_defaults_to_today_minus_window() -> None:
    start, end = _normalise_range(None, None, default_days=7)
    assert (end - start).days == 6
    assert end == datetime.now(UTC).date()


def test_normalise_range_rejects_inverted_window() -> None:
    today = datetime.now(UTC).date()
    with pytest.raises(InvalidRangeError):
        _normalise_range(today, today - timedelta(days=1), default_days=1)


def test_normalise_range_rejects_oversized_window() -> None:
    today = datetime.now(UTC).date()
    with pytest.raises(InvalidRangeError):
        _normalise_range(
            today - timedelta(days=10_000),
            today,
            default_days=1,
        )


def test_normalise_range_accepts_datetime_with_tz() -> None:
    start = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)
    end = datetime(2025, 1, 5, 23, 0, tzinfo=UTC)
    s, e = _normalise_range(start, end, default_days=1)
    assert s == date(2025, 1, 1)
    assert e == date(2025, 1, 5)


def test_build_funnel_computes_conversion_rates() -> None:
    counts = {"registered": 100, "activated": 80, "paid": 40, "repeat": 20, "premium": 5}
    stages = _build_funnel(counts)
    assert [s.key for s in stages] == [k for k, _ in FUNNEL_STAGES]
    paid = next(s for s in stages if s.key == "paid")
    # 40/100 from top, 40/80 from previous
    assert paid.conversion_from_top == pytest.approx(0.4)
    assert paid.conversion_from_previous == pytest.approx(0.5)
    # Premium row: 5/100 from top, 5/20 from previous
    premium = next(s for s in stages if s.key == "premium")
    assert premium.conversion_from_top == pytest.approx(0.05)
    assert premium.conversion_from_previous == pytest.approx(0.25)


def test_build_funnel_handles_empty_top() -> None:
    stages = _build_funnel({})
    assert all(s.users == 0 for s in stages)
    assert all(s.conversion_from_top == 0.0 for s in stages)
    assert all(s.conversion_from_previous == 0.0 for s in stages)


def test_revenue_csv_emits_header_and_rows() -> None:
    from app.services.analytics import RevenuePoint, RevenueSummary

    summary = RevenueSummary(
        start_date=date(2025, 5, 1),
        end_date=date(2025, 5, 2),
        group_by="day",
        total_stars=300,
        total_usd=Decimal("3.50"),
        total_tokens_sold=1500,
        total_purchases=2,
        points=[
            RevenuePoint(
                bucket=date(2025, 5, 1),
                stars=100,
                usd=Decimal("1.00"),
                tokens_sold=500,
                purchases=1,
            ),
            RevenuePoint(
                bucket=date(2025, 5, 2),
                stars=200,
                usd=Decimal("2.50"),
                tokens_sold=1000,
                purchases=1,
            ),
        ],
    )
    body = revenue_csv(summary)
    lines = body.strip().splitlines()
    assert lines[0] == "bucket,purchases,stars,usd,tokens_sold"
    assert lines[1] == "2025-05-01,1,100,1.00,500"
    assert lines[2] == "2025-05-02,1,200,2.50,1000"


# =========================================================================
# DB integration — real Postgres.
# =========================================================================


_NEXT_TID = 9_500_000


def _next_tid() -> int:
    global _NEXT_TID
    _NEXT_TID += 1
    return _NEXT_TID


async def _make_user(
    session,
    *,
    created_at: datetime | None = None,
    last_active_at: datetime | None = None,
    is_premium: bool = False,
    total_requests: int = 0,
) -> User:
    tid = _next_tid()
    user = User(
        telegram_id=tid,
        username=f"u{tid}",
        referral_code=f"AN-{tid}",
        token_balance=0,
        is_premium=is_premium,
        total_requests=total_requests,
    )
    session.add(user)
    await session.flush()
    if created_at is not None:
        user.created_at = created_at
    if last_active_at is not None:
        user.last_active_at = last_active_at
    await session.flush()
    return user


async def _make_purchase(
    session,
    *,
    user: User,
    stars: int,
    tokens: int,
    usd: Decimal | float | int = 0,
    created_at: datetime | None = None,
    completed: bool = True,
) -> Transaction:
    tx = Transaction(
        user_id=user.id,
        transaction_type="purchase",
        tokens_amount=tokens,
        stars_amount=stars,
        usd_amount=Decimal(str(usd)),
        package_name="starter",
        payment_status="completed" if completed else "pending",
        payment_method="telegram_stars",
    )
    session.add(tx)
    await session.flush()
    when = created_at or datetime.now(UTC)
    tx.created_at = when
    if completed:
        tx.completed_at = when
    await session.flush()
    return tx


async def _make_usage(
    session,
    *,
    user: User,
    service_type: str,
    tokens_consumed: int,
    created_at: datetime | None = None,
) -> TokenUsageLog:
    log = TokenUsageLog(
        user_id=user.id,
        service_type=service_type,
        tokens_consumed=tokens_consumed,
    )
    session.add(log)
    await session.flush()
    if created_at is not None:
        log.created_at = created_at
        await session.flush()
    return log


# ---------------------------------------------------------------- revenue


@pytest.mark.asyncio
async def test_get_revenue_summary_groups_by_day(db_session) -> None:
    user = await _make_user(db_session)
    today = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    yesterday = today - timedelta(days=1)
    await _make_purchase(db_session, user=user, stars=100, tokens=500, usd=1.0, created_at=today)
    await _make_purchase(db_session, user=user, stars=250, tokens=1000, usd=2.5, created_at=today)
    await _make_purchase(
        db_session, user=user, stars=50, tokens=200, usd=0.5, created_at=yesterday
    )

    summary = await get_revenue_summary(
        db_session,
        start_date=yesterday.date(),
        end_date=today.date(),
        group_by="day",
    )
    assert summary.group_by == "day"
    by_bucket = {p.bucket: p for p in summary.points}
    assert by_bucket[today.date()].stars == 350
    assert by_bucket[today.date()].tokens_sold == 1500
    assert by_bucket[today.date()].purchases == 2
    assert by_bucket[yesterday.date()].stars == 50
    assert summary.total_stars == 400
    assert summary.total_purchases == 3


@pytest.mark.asyncio
async def test_get_revenue_summary_ignores_pending_transactions(db_session) -> None:
    user = await _make_user(db_session)
    today = datetime.now(UTC)
    await _make_purchase(
        db_session, user=user, stars=999, tokens=999, usd=9.99, created_at=today, completed=False
    )
    summary = await get_revenue_summary(
        db_session,
        start_date=today.date(),
        end_date=today.date(),
        group_by="day",
    )
    assert summary.total_stars == 0
    assert summary.total_purchases == 0


@pytest.mark.asyncio
async def test_get_revenue_summary_rejects_invalid_group(db_session) -> None:
    with pytest.raises(UnsupportedGroupingError):
        await get_revenue_summary(db_session, group_by="hour")


# ---------------------------------------------------------------- behavior


@pytest.mark.asyncio
async def test_get_user_behavior_funnel_counts_paid_and_repeat(db_session) -> None:
    today = datetime.now(UTC)
    window_start = today - timedelta(days=3)

    # 5 registrations in the window.
    users = [
        await _make_user(db_session, created_at=window_start + timedelta(hours=i))
        for i in range(5)
    ]
    # 4 activated (one stays inactive).
    for u in users[:4]:
        await _make_usage(
            db_session, user=u, service_type="text_generation", tokens_consumed=1
        )
    # 3 paid; 2 of them paid twice → repeat.
    for u in users[:3]:
        await _make_purchase(
            db_session, user=u, stars=100, tokens=100, usd=1.0, created_at=today
        )
    for u in users[:2]:
        await _make_purchase(
            db_session, user=u, stars=200, tokens=200, usd=2.0, created_at=today
        )
    # 1 premium.
    users[0].is_premium = True
    await db_session.flush()

    behavior = await get_user_behavior(
        db_session,
        start_date=window_start.date(),
        end_date=today.date(),
        retention_weeks=2,
    )
    by_key = {s.key: s for s in behavior.funnel}
    assert by_key["registered"].users >= 5
    assert by_key["activated"].users >= 4
    assert by_key["paid"].users >= 3
    assert by_key["repeat"].users >= 2
    assert by_key["premium"].users >= 1


@pytest.mark.asyncio
async def test_get_user_behavior_includes_retention_rows(db_session) -> None:
    # Two users registered last week, both active in the same week → 100% week-0.
    base = datetime.now(UTC) - timedelta(days=2)
    u1 = await _make_user(db_session, created_at=base)
    u2 = await _make_user(db_session, created_at=base)
    await _make_usage(
        db_session, user=u1, service_type="image_generation", tokens_consumed=5, created_at=base
    )
    await _make_usage(
        db_session, user=u2, service_type="image_generation", tokens_consumed=5, created_at=base
    )

    behavior = await get_user_behavior(
        db_session,
        start_date=(base - timedelta(days=7)).date(),
        end_date=datetime.now(UTC).date(),
        retention_weeks=2,
    )
    assert behavior.retention_weeks == 2
    assert behavior.retention, "expected at least one cohort row"
    # At least one cohort row has 2 retained on week 0 — could be more if
    # other tests in the same session also created users in this window.
    week0 = [r.retained[0] for r in behavior.retention]
    assert max(week0) >= 2


# ---------------------------------------------------------------- LTV


@pytest.mark.asyncio
async def test_get_ltv_summary_attributes_revenue_to_cohort(db_session) -> None:
    # Register two users this month; one pays.
    this_month_start = datetime.now(UTC).replace(
        day=1, hour=10, minute=0, second=0, microsecond=0
    )
    payer = await _make_user(db_session, created_at=this_month_start)
    await _make_user(db_session, created_at=this_month_start)
    await _make_purchase(
        db_session, user=payer, stars=500, tokens=1000, usd=5.0,
        created_at=this_month_start + timedelta(days=1),
    )

    summary = await get_ltv_summary(db_session, months=3)
    # Find the cohort row for the current month.
    target_cohort = next(
        (c for c in summary.cohorts if c.cohort == this_month_start.date()),
        None,
    )
    assert target_cohort is not None
    assert target_cohort.cohort_size >= 2
    assert target_cohort.paying_users >= 1
    assert target_cohort.revenue_stars >= 500


# ---------------------------------------------------------------- tokens


@pytest.mark.asyncio
async def test_get_token_usage_sums_per_service(db_session) -> None:
    user = await _make_user(db_session)
    today = datetime.now(UTC)
    await _make_usage(
        db_session, user=user, service_type="text_generation", tokens_consumed=10, created_at=today
    )
    await _make_usage(
        db_session, user=user, service_type="text_generation", tokens_consumed=20, created_at=today
    )
    await _make_usage(
        db_session, user=user, service_type="image_generation", tokens_consumed=40, created_at=today
    )

    usage = await get_token_usage(
        db_session,
        start_date=today.date(),
        end_date=today.date(),
    )
    by_service = {p.service_type: p for p in usage.services}
    assert by_service["text_generation"].tokens_spent >= 30
    assert by_service["image_generation"].tokens_spent >= 40
    assert usage.total_tokens_spent >= 70
    # Shares add up to ~1.0 across reported services.
    assert sum(p.share for p in usage.services) == pytest.approx(1.0, abs=1e-6)


# ---------------------------------------------------------------- daily snapshot


@pytest.mark.asyncio
async def test_aggregate_daily_snapshot_upserts_row(db_session) -> None:
    target = datetime.now(UTC).date() - timedelta(days=1)
    lower = datetime.combine(target, datetime.min.time(), tzinfo=UTC) + timedelta(hours=2)
    user = await _make_user(
        db_session, created_at=lower, last_active_at=lower, is_premium=True
    )
    await _make_purchase(
        db_session, user=user, stars=400, tokens=500, usd=4.0, created_at=lower
    )
    await _make_usage(
        db_session, user=user, service_type="image_generation", tokens_consumed=15,
        created_at=lower,
    )

    result = await aggregate_daily_snapshot(db_session, snapshot_date=target)
    assert result.snapshot_date == target
    assert result.snapshot.new_users >= 1
    assert result.snapshot.active_users >= 1
    assert result.snapshot.premium_users >= 1
    assert result.snapshot.total_stars_revenue >= 400
    assert result.snapshot.total_tokens_sold >= 500
    assert result.snapshot.image_generations >= 1

    # Re-running for the same date must update in place, not insert duplicates.
    again = await aggregate_daily_snapshot(db_session, snapshot_date=target)
    assert again.created is False
    row = await db_session.get(DailyAnalytics, target)
    assert row is not None
    assert row.total_stars_revenue == result.snapshot.total_stars_revenue
