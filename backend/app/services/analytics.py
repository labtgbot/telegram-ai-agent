"""Admin analytics service (Phase 3, issue #27).

Powers the CRM "Analytics" section: revenue trends, conversion funnel,
cohort retention, and LTV.  The heavy lifting (group-by-date,
left-joins, generate_series) is delegated to PostgreSQL — these helpers
just assemble the SQL and shape the rows into dataclasses the API
layer can render verbatim.

The service is intentionally split into small functions per metric so
the daily aggregation worker (:mod:`app.workers.daily_analytics`) can
re-use the same primitives that the on-demand endpoints use.

All time inputs are interpreted as UTC; the API normalises whatever the
operator sent.  Date ranges are inclusive on both ends.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, cast

from sqlalchemy import and_, case, func, literal, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.daily_analytics import DailyAnalytics
from app.models.token_usage_log import TokenUsageLog
from app.models.transaction import Transaction
from app.models.user import User

logger = get_logger(__name__)


# ----------------------------------------------------------------- constants

GroupBy = Literal["day", "week", "month"]
ALLOWED_GROUPS: frozenset[str] = frozenset({"day", "week", "month"})

# Cap server-side aggregation windows to keep query latency bounded.
MAX_RANGE_DAYS: int = 366 * 3  # three years of daily data
DEFAULT_REVENUE_RANGE_DAYS: int = 30
DEFAULT_FUNNEL_RANGE_DAYS: int = 30
DEFAULT_RETENTION_WEEKS: int = 8
DEFAULT_LTV_COHORT_MONTHS: int = 6
DEFAULT_TOKEN_RANGE_DAYS: int = 30
MAX_CSV_ROWS: int = 50_000

ANALYTICS_AUDIT_EXPORT: str = "analytics.export_csv"


# ----------------------------------------------------------------- exceptions


class AnalyticsError(Exception):
    """Base class for analytics service failures."""


class InvalidRangeError(AnalyticsError):
    """start_date > end_date or the range is otherwise illegal."""


class UnsupportedGroupingError(AnalyticsError):
    """The requested ``group_by`` is not supported."""


# ----------------------------------------------------------------- dataclasses


@dataclass(frozen=True)
class RevenuePoint:
    bucket: date
    stars: int
    usd: Decimal
    tokens_sold: int
    purchases: int


@dataclass(frozen=True)
class RevenueSummary:
    start_date: date
    end_date: date
    group_by: str
    total_stars: int
    total_usd: Decimal
    total_tokens_sold: int
    total_purchases: int
    points: list[RevenuePoint]


@dataclass(frozen=True)
class FunnelStage:
    key: str
    label: str
    users: int
    conversion_from_previous: float
    conversion_from_top: float


@dataclass(frozen=True)
class RetentionRow:
    cohort: date
    cohort_size: int
    retained: list[int]  # absolute users retained on week 0,1,...,N
    rates: list[float]   # retained / cohort_size, same length


@dataclass(frozen=True)
class UserBehavior:
    start_date: date
    end_date: date
    funnel: list[FunnelStage]
    retention_weeks: int
    retention: list[RetentionRow]


@dataclass(frozen=True)
class LtvCohort:
    cohort: date  # first-of-month
    cohort_size: int
    paying_users: int
    revenue_stars: int
    revenue_usd: Decimal
    ltv_stars: float          # revenue_stars / cohort_size
    ltv_usd: float            # float(revenue_usd) / cohort_size
    avg_revenue_per_paying: float


@dataclass(frozen=True)
class LtvSummary:
    months: int
    cohorts: list[LtvCohort]
    overall_arpu_stars: float
    overall_arpu_usd: float
    overall_paying_rate: float


@dataclass(frozen=True)
class TokenUsagePoint:
    service_type: str
    requests: int
    tokens_spent: int
    share: float  # tokens_spent / total_tokens_spent (0..1)


@dataclass(frozen=True)
class TokenUsageSummary:
    start_date: date
    end_date: date
    total_requests: int
    total_tokens_spent: int
    services: list[TokenUsagePoint]


# ----------------------------------------------------------------- helpers


def _normalise_range(
    start: date | datetime | None,
    end: date | datetime | None,
    *,
    default_days: int,
) -> tuple[date, date]:
    today = datetime.now(UTC).date()
    end_d = _to_date(end) if end is not None else today
    start_d = _to_date(start) if start is not None else end_d - timedelta(days=default_days - 1)
    if start_d > end_d:
        raise InvalidRangeError("start_date must not be after end_date")
    if (end_d - start_d).days > MAX_RANGE_DAYS:
        raise InvalidRangeError(
            f"range exceeds {MAX_RANGE_DAYS} days — narrow start/end_date"
        )
    return start_d, end_d


def _to_date(value: date | datetime) -> date:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC).date()
    return value


def _coerce_group(value: str | None) -> GroupBy:
    raw = (value or "day").strip().lower()
    if raw not in ALLOWED_GROUPS:
        raise UnsupportedGroupingError(
            f"unsupported group_by={value!r}; expected day|week|month"
        )
    return cast(GroupBy, raw)


def _bucket_expr(column: Any, group_by: GroupBy) -> Any:
    """Build a ``date_trunc`` expression mapped back to a DATE."""
    return func.date_trunc(group_by, column).cast(DailyAnalytics.date.type)


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


# ----------------------------------------------------------------- revenue


async def get_revenue_summary(
    session: AsyncSession,
    *,
    start_date: date | datetime | None = None,
    end_date: date | datetime | None = None,
    group_by: str | None = "day",
) -> RevenueSummary:
    """Aggregate completed purchases by ``group_by`` bucket.

    Only ``transaction_type='purchase'`` rows count, and only those that
    finished — ``payment_status='completed'`` OR ``completed_at IS NOT NULL``.
    Refunds are subtracted from the stars/usd totals when they fall in
    the same bucket as the original purchase day.
    """
    grouping = _coerce_group(group_by)
    start, end = _normalise_range(
        start_date, end_date, default_days=DEFAULT_REVENUE_RANGE_DAYS
    )
    upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    lower = datetime.combine(start, datetime.min.time(), tzinfo=UTC)

    bucket = _bucket_expr(Transaction.created_at, grouping).label("bucket")
    revenue_filter = and_(
        Transaction.created_at >= lower,
        Transaction.created_at < upper,
        Transaction.transaction_type == "purchase",
        or_(
            Transaction.payment_status == "completed",
            Transaction.completed_at.is_not(None),
        ),
    )

    stmt = (
        select(
            bucket,
            func.coalesce(func.sum(Transaction.stars_amount), 0).label("stars"),
            func.coalesce(func.sum(Transaction.usd_amount), 0).label("usd"),
            func.coalesce(func.sum(Transaction.tokens_amount), 0).label("tokens"),
            func.count(Transaction.id).label("purchases"),
        )
        .where(revenue_filter)
        .group_by(bucket)
        .order_by(bucket.asc())
    )

    rows = (await session.execute(stmt)).all()
    points: list[RevenuePoint] = []
    total_stars = 0
    total_usd = Decimal("0")
    total_tokens = 0
    total_purchases = 0
    for row in rows:
        bucket_value = _to_date(row.bucket)
        stars = int(row.stars or 0)
        usd = Decimal(row.usd or 0)
        tokens = int(row.tokens or 0)
        purchases = int(row.purchases or 0)
        points.append(
            RevenuePoint(
                bucket=bucket_value,
                stars=stars,
                usd=usd,
                tokens_sold=tokens,
                purchases=purchases,
            )
        )
        total_stars += stars
        total_usd += usd
        total_tokens += tokens
        total_purchases += purchases

    return RevenueSummary(
        start_date=start,
        end_date=end,
        group_by=grouping,
        total_stars=total_stars,
        total_usd=total_usd,
        total_tokens_sold=total_tokens,
        total_purchases=total_purchases,
        points=points,
    )


# ----------------------------------------------------------------- funnel


# Stage definitions, ordered top → bottom.  Keys map to keys returned by
# ``_funnel_counts`` so the SQL only runs once per request.
FUNNEL_STAGES: tuple[tuple[str, str], ...] = (
    ("registered", "Registered"),
    ("activated", "Used the bot"),
    ("paid", "Made a purchase"),
    ("repeat", "Repeat purchase"),
    ("premium", "Premium"),
)


async def _funnel_counts(
    session: AsyncSession,
    *,
    start: date,
    end: date,
) -> dict[str, int]:
    upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    lower = datetime.combine(start, datetime.min.time(), tzinfo=UTC)

    # Registered: account created in the window.
    registered_stmt = (
        select(func.count(User.id))
        .where(User.created_at >= lower, User.created_at < upper)
    )

    # Activated: registered AND has at least one row in token_usage_logs
    # OR ``total_requests > 0``.
    activated_stmt = (
        select(func.count(User.id.distinct()))
        .where(User.created_at >= lower, User.created_at < upper)
        .where(
            or_(
                User.total_requests > 0,
                User.id.in_(
                    select(TokenUsageLog.user_id).where(
                        TokenUsageLog.created_at >= lower,
                    )
                ),
            )
        )
    )

    # Paid: registered in window AND has any completed purchase ever.
    paid_subq = (
        select(Transaction.user_id)
        .where(
            Transaction.transaction_type == "purchase",
            or_(
                Transaction.payment_status == "completed",
                Transaction.completed_at.is_not(None),
            ),
        )
    )
    paid_stmt = (
        select(func.count(User.id.distinct()))
        .where(User.created_at >= lower, User.created_at < upper)
        .where(User.id.in_(paid_subq))
    )

    # Repeat: ≥ 2 completed purchases.
    repeat_subq = (
        select(Transaction.user_id)
        .where(
            Transaction.transaction_type == "purchase",
            or_(
                Transaction.payment_status == "completed",
                Transaction.completed_at.is_not(None),
            ),
        )
        .group_by(Transaction.user_id)
        .having(func.count(Transaction.id) >= 2)
    )
    repeat_stmt = (
        select(func.count(User.id.distinct()))
        .where(User.created_at >= lower, User.created_at < upper)
        .where(User.id.in_(repeat_subq))
    )

    # Premium: is_premium flag flipped.
    premium_stmt = (
        select(func.count(User.id))
        .where(User.created_at >= lower, User.created_at < upper)
        .where(User.is_premium.is_(True))
    )

    return {
        "registered": int((await session.execute(registered_stmt)).scalar_one() or 0),
        "activated": int((await session.execute(activated_stmt)).scalar_one() or 0),
        "paid": int((await session.execute(paid_stmt)).scalar_one() or 0),
        "repeat": int((await session.execute(repeat_stmt)).scalar_one() or 0),
        "premium": int((await session.execute(premium_stmt)).scalar_one() or 0),
    }


def _build_funnel(counts: dict[str, int]) -> list[FunnelStage]:
    top = counts.get(FUNNEL_STAGES[0][0], 0)
    stages: list[FunnelStage] = []
    previous = top
    for key, label in FUNNEL_STAGES:
        users = int(counts.get(key, 0))
        from_top = _safe_div(users, top)
        from_prev = _safe_div(users, previous) if previous else 0.0
        stages.append(
            FunnelStage(
                key=key,
                label=label,
                users=users,
                conversion_from_previous=from_prev,
                conversion_from_top=from_top,
            )
        )
        previous = users
    return stages


# ----------------------------------------------------------------- retention


async def _retention_matrix(
    session: AsyncSession,
    *,
    start: date,
    end: date,
    weeks: int,
) -> list[RetentionRow]:
    """Weekly cohort retention starting at the Monday containing ``start``.

    ``cohort`` = ISO Monday of the user's ``created_at`` week.
    ``retained[k]`` = users who logged an activity (token_usage_log) in
    week k after their cohort week (week 0 = sign-up week).
    """
    if weeks < 1:
        return []
    weeks = min(weeks, 26)

    monday = start - timedelta(days=start.weekday())
    upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    lower = datetime.combine(monday, datetime.min.time(), tzinfo=UTC)

    # Cohorts = users whose week-of-registration falls in [monday, end].
    cohort_expr = func.date_trunc("week", User.created_at).cast(DailyAnalytics.date.type)
    cohort_stmt = (
        select(cohort_expr.label("cohort"), func.count(User.id).label("size"))
        .where(User.created_at >= lower, User.created_at < upper)
        .group_by(cohort_expr)
        .order_by(cohort_expr.asc())
    )
    cohort_rows = (await session.execute(cohort_stmt)).all()
    if not cohort_rows:
        return []

    activity_cohort = func.date_trunc("week", User.created_at).cast(
        DailyAnalytics.date.type
    )
    activity_week = func.date_trunc("week", TokenUsageLog.created_at).cast(
        DailyAnalytics.date.type
    )
    week_offset = (
        (
            func.extract("epoch", activity_week)
            - func.extract("epoch", activity_cohort)
        )
        / literal(60 * 60 * 24 * 7)
    ).cast(DailyAnalytics.total_users.type)

    activity_stmt = (
        select(
            activity_cohort.label("cohort"),
            week_offset.label("week"),
            func.count(TokenUsageLog.user_id.distinct()).label("active"),
        )
        .join(User, User.id == TokenUsageLog.user_id)
        .where(User.created_at >= lower, User.created_at < upper)
        .where(TokenUsageLog.created_at >= lower)
        .group_by(activity_cohort, week_offset)
    )
    activity_rows = (await session.execute(activity_stmt)).all()
    matrix: dict[date, list[int]] = {}
    for row in cohort_rows:
        cohort_date = _to_date(row.cohort)
        matrix[cohort_date] = [0] * weeks

    for row in activity_rows:
        cohort_date = _to_date(row.cohort)
        wk = int(row.week or 0)
        if 0 <= wk < weeks and cohort_date in matrix:
            matrix[cohort_date][wk] = int(row.active or 0)

    results: list[RetentionRow] = []
    for row in cohort_rows:
        cohort_date = _to_date(row.cohort)
        size = int(row.size or 0)
        retained = matrix.get(cohort_date, [0] * weeks)
        rates = [_safe_div(value, size) for value in retained]
        results.append(
            RetentionRow(
                cohort=cohort_date,
                cohort_size=size,
                retained=retained,
                rates=rates,
            )
        )
    return results


async def get_user_behavior(
    session: AsyncSession,
    *,
    start_date: date | datetime | None = None,
    end_date: date | datetime | None = None,
    retention_weeks: int = DEFAULT_RETENTION_WEEKS,
) -> UserBehavior:
    start, end = _normalise_range(
        start_date, end_date, default_days=DEFAULT_FUNNEL_RANGE_DAYS
    )
    counts = await _funnel_counts(session, start=start, end=end)
    funnel = _build_funnel(counts)
    retention = await _retention_matrix(
        session, start=start, end=end, weeks=int(retention_weeks)
    )
    return UserBehavior(
        start_date=start,
        end_date=end,
        funnel=funnel,
        retention_weeks=int(retention_weeks),
        retention=retention,
    )


# ----------------------------------------------------------------- LTV


async def get_ltv_summary(
    session: AsyncSession,
    *,
    months: int = DEFAULT_LTV_COHORT_MONTHS,
) -> LtvSummary:
    """Lifetime value per monthly cohort, looking back ``months`` months.

    A cohort is the first-of-month of ``users.created_at``.  Revenue is
    every completed purchase the cohort made since registration —
    "lifetime" in the per-cohort sense.
    """
    months = max(1, min(int(months), 24))
    today = datetime.now(UTC).date().replace(day=1)
    # Earliest first-of-month included in the report.
    cohort_start = today
    for _ in range(months - 1):
        # Walk back one month at a time using replace(day=1) - 1 day - replace
        prev_last = cohort_start - timedelta(days=1)
        cohort_start = prev_last.replace(day=1)
    upper = datetime.combine(
        (today + timedelta(days=32)).replace(day=1),
        datetime.min.time(),
        tzinfo=UTC,
    )
    lower = datetime.combine(cohort_start, datetime.min.time(), tzinfo=UTC)

    cohort_expr = func.date_trunc("month", User.created_at).cast(
        DailyAnalytics.date.type
    )
    cohort_stmt = (
        select(cohort_expr.label("cohort"), func.count(User.id).label("size"))
        .where(User.created_at >= lower, User.created_at < upper)
        .group_by(cohort_expr)
        .order_by(cohort_expr.asc())
    )
    cohort_rows = (await session.execute(cohort_stmt)).all()
    cohort_size: dict[date, int] = {
        _to_date(row.cohort): int(row.size or 0) for row in cohort_rows
    }
    if not cohort_size:
        return LtvSummary(
            months=months,
            cohorts=[],
            overall_arpu_stars=0.0,
            overall_arpu_usd=0.0,
            overall_paying_rate=0.0,
        )

    revenue_cohort = func.date_trunc("month", User.created_at).cast(
        DailyAnalytics.date.type
    )
    revenue_stmt = (
        select(
            revenue_cohort.label("cohort"),
            func.count(Transaction.user_id.distinct()).label("paying"),
            func.coalesce(func.sum(Transaction.stars_amount), 0).label("stars"),
            func.coalesce(func.sum(Transaction.usd_amount), 0).label("usd"),
        )
        .join(User, User.id == Transaction.user_id)
        .where(User.created_at >= lower, User.created_at < upper)
        .where(
            Transaction.transaction_type == "purchase",
            or_(
                Transaction.payment_status == "completed",
                Transaction.completed_at.is_not(None),
            ),
        )
        .group_by(revenue_cohort)
    )
    revenue_rows = (await session.execute(revenue_stmt)).all()
    revenue_map: dict[date, dict[str, Any]] = {}
    for row in revenue_rows:
        cohort_date = _to_date(row.cohort)
        revenue_map[cohort_date] = {
            "paying": int(row.paying or 0),
            "stars": int(row.stars or 0),
            "usd": Decimal(row.usd or 0),
        }

    cohorts: list[LtvCohort] = []
    total_size = 0
    total_stars = 0
    total_usd = Decimal("0")
    total_paying = 0
    for cohort_date, size in cohort_size.items():
        bucket = revenue_map.get(cohort_date, {"paying": 0, "stars": 0, "usd": Decimal("0")})
        stars = int(bucket["stars"])
        usd = Decimal(bucket["usd"])
        paying = int(bucket["paying"])
        ltv_stars = _safe_div(stars, size)
        ltv_usd = _safe_div(float(usd), size)
        arpp = _safe_div(stars, paying)
        cohorts.append(
            LtvCohort(
                cohort=cohort_date,
                cohort_size=size,
                paying_users=paying,
                revenue_stars=stars,
                revenue_usd=usd,
                ltv_stars=ltv_stars,
                ltv_usd=ltv_usd,
                avg_revenue_per_paying=arpp,
            )
        )
        total_size += size
        total_stars += stars
        total_usd += usd
        total_paying += paying

    return LtvSummary(
        months=months,
        cohorts=cohorts,
        overall_arpu_stars=_safe_div(total_stars, total_size),
        overall_arpu_usd=_safe_div(float(total_usd), total_size),
        overall_paying_rate=_safe_div(total_paying, total_size),
    )


# ----------------------------------------------------------------- tokens


async def get_token_usage(
    session: AsyncSession,
    *,
    start_date: date | datetime | None = None,
    end_date: date | datetime | None = None,
) -> TokenUsageSummary:
    start, end = _normalise_range(
        start_date, end_date, default_days=DEFAULT_TOKEN_RANGE_DAYS
    )
    lower = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC)

    stmt = (
        select(
            TokenUsageLog.service_type.label("service"),
            func.count(TokenUsageLog.id).label("requests"),
            func.coalesce(func.sum(TokenUsageLog.tokens_consumed), 0).label("tokens"),
        )
        .where(TokenUsageLog.created_at >= lower, TokenUsageLog.created_at < upper)
        .group_by(TokenUsageLog.service_type)
        .order_by(func.sum(TokenUsageLog.tokens_consumed).desc())
    )
    rows = (await session.execute(stmt)).all()
    total_requests = sum(int(row.requests or 0) for row in rows)
    total_tokens = sum(int(row.tokens or 0) for row in rows)
    services: list[TokenUsagePoint] = []
    for row in rows:
        tokens = int(row.tokens or 0)
        services.append(
            TokenUsagePoint(
                service_type=str(row.service or "unknown"),
                requests=int(row.requests or 0),
                tokens_spent=tokens,
                share=_safe_div(tokens, total_tokens),
            )
        )
    return TokenUsageSummary(
        start_date=start,
        end_date=end,
        total_requests=total_requests,
        total_tokens_spent=total_tokens,
        services=services,
    )


# --------------------------------------------------------------- daily snapshot


@dataclass(frozen=True)
class DailySnapshotResult:
    snapshot_date: date
    created: bool  # True when a new row was inserted, False when updated
    snapshot: DailyAnalytics


async def aggregate_daily_snapshot(
    session: AsyncSession,
    *,
    snapshot_date: date | None = None,
) -> DailySnapshotResult:
    """Upsert one row in ``daily_analytics`` for ``snapshot_date``.

    Idempotent: re-running for the same day rewrites the same numbers.
    The caller owns the transaction (used by the worker, which commits
    once at the end).
    """
    target = snapshot_date or (datetime.now(UTC).date() - timedelta(days=1))
    lower = datetime.combine(target, datetime.min.time(), tzinfo=UTC)
    upper = lower + timedelta(days=1)

    users_total_stmt = select(func.count(User.id)).where(User.created_at < upper)
    new_users_stmt = (
        select(func.count(User.id))
        .where(User.created_at >= lower, User.created_at < upper)
    )
    active_stmt = (
        select(func.count(User.id.distinct()))
        .where(User.last_active_at >= lower, User.last_active_at < upper)
    )
    premium_stmt = (
        select(func.count(User.id))
        .where(User.is_premium.is_(True), User.created_at < upper)
    )

    revenue_stmt = select(
        func.coalesce(func.sum(Transaction.tokens_amount), 0).label("tokens"),
        func.coalesce(func.sum(Transaction.stars_amount), 0).label("stars"),
        func.coalesce(func.sum(Transaction.usd_amount), 0).label("usd"),
    ).where(
        Transaction.transaction_type == "purchase",
        or_(
            Transaction.payment_status == "completed",
            Transaction.completed_at.is_not(None),
        ),
        Transaction.created_at >= lower,
        Transaction.created_at < upper,
    )

    usage_total_stmt = (
        select(func.count(TokenUsageLog.id))
        .where(TokenUsageLog.created_at >= lower, TokenUsageLog.created_at < upper)
    )
    image_stmt = (
        select(func.count(TokenUsageLog.id))
        .where(
            TokenUsageLog.created_at >= lower,
            TokenUsageLog.created_at < upper,
            TokenUsageLog.service_type == "image_generation",
        )
    )
    video_stmt = (
        select(func.count(TokenUsageLog.id))
        .where(
            TokenUsageLog.created_at >= lower,
            TokenUsageLog.created_at < upper,
            TokenUsageLog.service_type == "video_generation",
        )
    )
    text_stmt = (
        select(func.count(TokenUsageLog.id))
        .where(
            TokenUsageLog.created_at >= lower,
            TokenUsageLog.created_at < upper,
            TokenUsageLog.service_type == "text_generation",
        )
    )
    tokens_per_user_stmt = select(
        func.coalesce(
            func.avg(TokenUsageLog.tokens_consumed),
            0,
        )
    ).where(TokenUsageLog.created_at >= lower, TokenUsageLog.created_at < upper)

    total_users = int((await session.execute(users_total_stmt)).scalar_one() or 0)
    new_users = int((await session.execute(new_users_stmt)).scalar_one() or 0)
    active_users = int((await session.execute(active_stmt)).scalar_one() or 0)
    premium_users = int((await session.execute(premium_stmt)).scalar_one() or 0)

    revenue_row = (await session.execute(revenue_stmt)).one()
    total_tokens_sold = int(revenue_row.tokens or 0)
    total_stars = int(revenue_row.stars or 0)
    total_usd = Decimal(revenue_row.usd or 0)

    total_requests = int((await session.execute(usage_total_stmt)).scalar_one() or 0)
    image_generations = int((await session.execute(image_stmt)).scalar_one() or 0)
    video_generations = int((await session.execute(video_stmt)).scalar_one() or 0)
    text_queries = int((await session.execute(text_stmt)).scalar_one() or 0)
    avg_tokens = Decimal((await session.execute(tokens_per_user_stmt)).scalar_one() or 0)

    conversion_rate: Decimal | None = None
    if total_users > 0:
        conversion_rate = (Decimal(premium_users) * Decimal(100) / Decimal(total_users)).quantize(
            Decimal("0.01")
        )

    snapshot = await session.get(DailyAnalytics, target)
    created = snapshot is None
    if snapshot is None:
        snapshot = DailyAnalytics(date=target)
        session.add(snapshot)

    snapshot.total_users = total_users
    snapshot.new_users = new_users
    snapshot.active_users = active_users
    snapshot.premium_users = premium_users
    snapshot.total_tokens_sold = total_tokens_sold
    snapshot.total_stars_revenue = total_stars
    snapshot.total_usd_revenue = total_usd
    snapshot.total_requests = total_requests
    snapshot.image_generations = image_generations
    snapshot.video_generations = video_generations
    snapshot.text_queries = text_queries
    snapshot.avg_tokens_per_user = (
        Decimal(avg_tokens).quantize(Decimal("0.01")) if avg_tokens else None
    )
    snapshot.conversion_rate = conversion_rate

    await session.flush()
    return DailySnapshotResult(snapshot_date=target, created=created, snapshot=snapshot)


# ------------------------------------------------------------------- CSV export


REVENUE_CSV_COLUMNS: tuple[str, ...] = (
    "bucket",
    "purchases",
    "stars",
    "usd",
    "tokens_sold",
)


def revenue_csv(summary: RevenueSummary) -> str:
    """Render a :class:`RevenueSummary` as CSV."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(REVENUE_CSV_COLUMNS)
    for point in summary.points:
        writer.writerow(
            [
                point.bucket.isoformat(),
                point.purchases,
                point.stars,
                f"{point.usd:.2f}",
                point.tokens_sold,
            ]
        )
    return buffer.getvalue()
