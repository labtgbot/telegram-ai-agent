"""Partition maintenance helpers for ``token_usage_logs``.

The table is range-partitioned by ``created_at``. A DEFAULT partition keeps
unexpected future writes from failing, while this module creates regular
monthly partitions ahead of time so normal traffic stays on bounded children.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from textwrap import dedent

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TOKEN_USAGE_PARENT_TABLE = "token_usage_logs"
TOKEN_USAGE_DEFAULT_PARTITION = "token_usage_logs_default"
DEFAULT_MONTHS_AHEAD = 6
_ADVISORY_LOCK_ID = 5487867697498010867
_COLUMNS = (
    "id",
    "user_id",
    "service_type",
    "tokens_consumed",
    "request_params",
    "response_status",
    "processing_time_ms",
    "composio_tool",
    "mcp_server",
    "created_at",
)
_COLUMNS_SQL = ", ".join(_COLUMNS)


@dataclass(frozen=True)
class TokenUsagePartitionMaintenanceResult:
    """Summary of one partition maintenance pass."""

    default_created: bool
    partitions_created: tuple[str, ...]
    rows_moved: int = 0


def month_start(value: datetime) -> datetime:
    """Return ``value`` normalized to the first instant of its UTC month."""
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def add_months(value: datetime, months: int) -> datetime:
    """Add whole calendar months to a UTC month-start datetime."""
    total = value.year * 12 + (value.month - 1) + months
    year, zero_based_month = divmod(total, 12)
    return value.replace(year=year, month=zero_based_month + 1)


def partition_name_for_month(start: datetime) -> str:
    return f"token_usage_logs_{start.strftime('%Y_%m')}"


def iter_month_ranges(start: datetime, *, months_ahead: int) -> Iterator[tuple[datetime, datetime]]:
    if months_ahead < 0:
        raise ValueError("months_ahead must be >= 0")
    current = month_start(start)
    for offset in range(months_ahead + 1):
        lower = add_months(current, offset)
        yield lower, add_months(lower, 1)


async def ensure_token_usage_partitions(
    session: AsyncSession,
    *,
    reference_date: datetime | None = None,
    months_ahead: int = DEFAULT_MONTHS_AHEAD,
) -> TokenUsagePartitionMaintenanceResult:
    """Ensure DEFAULT plus current/future monthly partitions exist.

    ``months_ahead`` counts months after the reference month. The reference
    month itself is always checked too, so the default creates current + six.
    """
    if months_ahead < 0:
        raise ValueError("months_ahead must be >= 0")

    await session.execute(
        text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": _ADVISORY_LOCK_ID}
    )

    default_created = await _ensure_default_partition(session)
    created: list[str] = []
    rows_moved = 0
    start = month_start(reference_date or datetime.now(UTC))
    for lower, upper in iter_month_ranges(start, months_ahead=months_ahead):
        partition_name = partition_name_for_month(lower)
        if await _partition_exists(session, partition_name):
            continue
        moved = await _create_monthly_partition(session, partition_name, lower, upper)
        rows_moved += moved
        created.append(partition_name)

    return TokenUsagePartitionMaintenanceResult(
        default_created=default_created,
        partitions_created=tuple(created),
        rows_moved=rows_moved,
    )


async def _ensure_default_partition(session: AsyncSession) -> bool:
    if await _default_partition_exists(session):
        return False
    await session.execute(
        _sql(f"""
            CREATE TABLE {TOKEN_USAGE_DEFAULT_PARTITION}
            PARTITION OF {TOKEN_USAGE_PARENT_TABLE}
            DEFAULT
            """)
    )
    return True


async def _default_partition_exists(session: AsyncSession) -> bool:
    result = await session.execute(
        _sql("""
            SELECT EXISTS (
                SELECT 1
                FROM pg_inherits
                JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
                JOIN pg_class child ON child.oid = pg_inherits.inhrelid
                WHERE parent.relname = :parent_table
                  AND pg_get_expr(child.relpartbound, child.oid) = 'DEFAULT'
            )
            """),
        {"parent_table": TOKEN_USAGE_PARENT_TABLE},
    )
    return bool(result.scalar_one())


async def _partition_exists(session: AsyncSession, partition_name: str) -> bool:
    result = await session.execute(
        _sql("""
            SELECT EXISTS (
                SELECT 1
                FROM pg_inherits
                JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
                JOIN pg_class child ON child.oid = pg_inherits.inhrelid
                WHERE parent.relname = :parent_table
                  AND child.relname = :partition_name
            )
            """),
        {
            "parent_table": TOKEN_USAGE_PARENT_TABLE,
            "partition_name": partition_name,
        },
    )
    return bool(result.scalar_one())


async def _create_monthly_partition(
    session: AsyncSession,
    partition_name: str,
    lower: datetime,
    upper: datetime,
) -> int:
    temp_name = f"token_usage_logs_rehome_{lower.strftime('%Y_%m')}"
    lower_sql = _timestamp_literal(lower)
    upper_sql = _timestamp_literal(upper)

    await session.execute(
        _sql(f"""
            LOCK TABLE {TOKEN_USAGE_DEFAULT_PARTITION} IN ACCESS EXCLUSIVE MODE
            """)
    )
    rows_to_move = await _count_default_rows_in_range(session, lower_sql, upper_sql)

    if rows_to_move:
        await session.execute(
            _sql(f"""
                CREATE TEMP TABLE {temp_name} ON COMMIT DROP AS
                SELECT {_COLUMNS_SQL}
                FROM {TOKEN_USAGE_DEFAULT_PARTITION}
                WHERE false
                """)
        )
        await session.execute(
            _sql(f"""
                INSERT INTO {temp_name} ({_COLUMNS_SQL})
                SELECT {_COLUMNS_SQL}
                FROM {TOKEN_USAGE_DEFAULT_PARTITION}
                WHERE created_at >= TIMESTAMPTZ '{lower_sql}'
                  AND created_at < TIMESTAMPTZ '{upper_sql}'
                """)
        )
        await session.execute(
            _sql(f"""
                DELETE FROM {TOKEN_USAGE_DEFAULT_PARTITION}
                WHERE created_at >= TIMESTAMPTZ '{lower_sql}'
                  AND created_at < TIMESTAMPTZ '{upper_sql}'
                """)
        )

    await session.execute(
        _sql(f"""
            CREATE TABLE {partition_name}
            PARTITION OF {TOKEN_USAGE_PARENT_TABLE}
            FOR VALUES FROM ('{lower_sql}') TO ('{upper_sql}')
            """)
    )

    if rows_to_move:
        await session.execute(
            _sql(f"""
                INSERT INTO {TOKEN_USAGE_PARENT_TABLE} ({_COLUMNS_SQL})
                SELECT {_COLUMNS_SQL}
                FROM {temp_name}
                """)
        )

    return rows_to_move


async def _count_default_rows_in_range(
    session: AsyncSession,
    lower_sql: str,
    upper_sql: str,
) -> int:
    result = await session.execute(
        _sql(f"""
            SELECT count(*)
            FROM {TOKEN_USAGE_DEFAULT_PARTITION}
            WHERE created_at >= TIMESTAMPTZ '{lower_sql}'
              AND created_at < TIMESTAMPTZ '{upper_sql}'
            """)
    )
    return int(result.scalar_one())


def _timestamp_literal(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _sql(statement: str):
    return text(dedent(statement).strip())
