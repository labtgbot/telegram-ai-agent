"""Monthly partition maintenance worker for ``token_usage_logs``.

Run this from cron, Kubernetes CronJob, or Celery beat before month-end:
``python -m app.workers.token_usage_partitions``.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.services.token_usage_partitions import (
    DEFAULT_MONTHS_AHEAD,
    TokenUsagePartitionMaintenanceResult,
    ensure_token_usage_partitions,
)

logger = get_logger(__name__)


async def run_token_usage_partition_maintenance(
    *,
    reference_date: datetime | None = None,
    months_ahead: int = DEFAULT_MONTHS_AHEAD,
) -> TokenUsagePartitionMaintenanceResult:
    """Create missing token usage partitions and commit the pass."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await ensure_token_usage_partitions(
                session,
                reference_date=reference_date,
                months_ahead=months_ahead,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("token_usage.partitions.failed")
            raise
    logger.info(
        "token_usage.partitions.summary",
        default_created=result.default_created,
        partitions_created=len(result.partitions_created),
        rows_moved=result.rows_moved,
    )
    return result


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.workers.token_usage_partitions",
        description="Create token_usage_logs monthly partitions ahead of time.",
    )
    parser.add_argument(
        "--months-ahead",
        type=int,
        default=DEFAULT_MONTHS_AHEAD,
        help="Number of future months to pre-create after the reference month.",
    )
    parser.add_argument(
        "--reference-date",
        type=datetime.fromisoformat,
        default=None,
        help="Reference date for partition planning, ISO-8601 format.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = asyncio.run(
            run_token_usage_partition_maintenance(
                reference_date=args.reference_date,
                months_ahead=args.months_ahead,
            )
        )
    except Exception:  # noqa: BLE001 — already logged above
        return 1
    print(  # noqa: T201 — CLI summary line
        f"default_created={int(result.default_created)} "
        f"partitions_created={len(result.partitions_created)} "
        f"rows_moved={result.rows_moved}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
