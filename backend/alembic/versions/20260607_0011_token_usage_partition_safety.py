"""token usage partition safety net

Revision ID: 0011_token_usage_partitions
Revises: 0010_account_deletion
Create Date: 2026-06-07

Adds a DEFAULT partition for ``token_usage_logs`` and extends the initial
monthly partition window. Ongoing rotation is handled by
``app.workers.token_usage_partitions``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from textwrap import dedent

from alembic import op

revision: str = "0011_token_usage_partitions"
down_revision: str | Sequence[str] | None = "0010_account_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PARTITION_LOOKAHEAD_MONTHS = 6


def _first_of_month(d: datetime) -> datetime:
    return d.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(d: datetime) -> datetime:
    return _first_of_month(d.replace(day=28) + timedelta(days=4))


def upgrade() -> None:
    op.execute(
        _sql("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_inherits
                JOIN pg_class parent ON parent.oid = pg_inherits.inhparent
                JOIN pg_class child ON child.oid = pg_inherits.inhrelid
                WHERE parent.relname = 'token_usage_logs'
                  AND pg_get_expr(child.relpartbound, child.oid) = 'DEFAULT'
            ) THEN
                CREATE TABLE token_usage_logs_default
                PARTITION OF token_usage_logs
                DEFAULT;
            END IF;
        END $$;
        """)
    )

    current = _first_of_month(datetime.now(UTC))
    start = current
    for _ in range(PARTITION_LOOKAHEAD_MONTHS + 1):
        end = _next_month(start)
        partition_name = f"token_usage_logs_{start.strftime('%Y_%m')}"
        op.execute(
            _sql(f"""
            DO $$
            BEGIN
                IF to_regclass('public.{partition_name}') IS NULL THEN
                    CREATE TABLE {partition_name}
                    PARTITION OF token_usage_logs
                    FOR VALUES FROM ('{start.isoformat()}') TO ('{end.isoformat()}');
                END IF;
            END $$;
            """)
        )
        start = end


def downgrade() -> None:
    current = _first_of_month(datetime.now(UTC))
    start = current
    for _ in range(PARTITION_LOOKAHEAD_MONTHS + 1):
        partition_name = f"token_usage_logs_{start.strftime('%Y_%m')}"
        if start >= _next_month(current):
            op.execute(f"DROP TABLE IF EXISTS {partition_name};")
        start = _next_month(start)

    op.execute("DROP TABLE IF EXISTS token_usage_logs_default;")


def _sql(statement: str) -> str:
    return dedent(statement).strip()
