"""Daily analytics aggregation worker (Phase 3, issue #27).

Designed to be invoked once per day by an external scheduler (cron, k8s
CronJob, Celery beat) shortly after midnight UTC.  Computes a single
``daily_analytics`` row for the previous calendar day so the
``/admin/analytics`` endpoints can serve pre-aggregated KPIs in O(1)
instead of scanning the raw transactions table on every page load.

Phase 3 keeps the worker as a thin CLI entrypoint ``python -m
app.workers.daily_analytics``.  Phase 4 will wire it into Celery beat
alongside the renewal sweep (see ``docs/ARCHITECTURE.md > Workers``).

The function is idempotent — re-running for the same date rewrites the
same row, so cron can safely retry on transient DB errors.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, date, datetime, timedelta

from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.services.analytics import DailySnapshotResult, aggregate_daily_snapshot

logger = get_logger(__name__)


async def run_daily_analytics(
    *,
    snapshot_date: date | None = None,
) -> DailySnapshotResult:
    """Aggregate a single ``daily_analytics`` row and commit.

    ``snapshot_date`` defaults to yesterday (UTC).  Errors are logged
    and re-raised so the scheduler can mark the run as failed.
    """
    target = snapshot_date or (datetime.now(UTC).date() - timedelta(days=1))
    factory = get_session_factory()
    async with factory() as session:
        try:
            result = await aggregate_daily_snapshot(session, snapshot_date=target)
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("analytics.daily.failed", target=target.isoformat())
            raise
    logger.info(
        "analytics.daily.snapshot",
        date=result.snapshot_date.isoformat(),
        created=result.created,
        new_users=result.snapshot.new_users,
        active_users=result.snapshot.active_users,
        stars_revenue=result.snapshot.total_stars_revenue,
    )
    return result


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.workers.daily_analytics",
        description="Build the daily_analytics snapshot for one date.",
    )
    parser.add_argument(
        "--date",
        dest="date",
        type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
        default=None,
        help="Target date in YYYY-MM-DD (default: yesterday UTC).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: ``python -m app.workers.daily_analytics [--date YYYY-MM-DD]``."""
    args = _parse_args(argv)
    try:
        result = asyncio.run(run_daily_analytics(snapshot_date=args.date))
    except Exception:  # noqa: BLE001 — already logged above
        return 1
    print(  # noqa: T201 — CLI output
        f"snapshot_date={result.snapshot_date.isoformat()} "
        f"created={int(result.created)} "
        f"new_users={result.snapshot.new_users} "
        f"active_users={result.snapshot.active_users} "
        f"stars_revenue={result.snapshot.total_stars_revenue}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
