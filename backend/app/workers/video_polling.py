"""Video-job polling worker.

Designed to be invoked on a short interval (every 5–30s) by an external
scheduler — cron, k8s ``CronJob``, or a long-running supervisor process
that calls :func:`run_video_polling_loop`.  Iterates every non-terminal
``video_jobs`` row and asks the Composio video toolkit for its current
status, then:

* persists the new state (``queued`` → ``in_progress`` → ``succeeded``);
* refunds the up-front token spend on confirmed provider failure;
* writes a zero-cost ``token_usage_logs`` row on failure for the audit
  trail.

The work itself lives in :class:`app.services.video_generation.VideoGenerationService`
— this module is a thin entrypoint that owns the database session and
the ``ComposioClient`` lifecycle.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import TYPE_CHECKING

from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.services.composio import build_client
from app.services.video_generation import VideoGenerationService, VideoJobView

if TYPE_CHECKING:
    from app.services.composio import ComposioClient

logger = get_logger(__name__)


async def run_video_polling_pass(
    *,
    limit: int = 100,
    composio: ComposioClient | None = None,
) -> list[VideoJobView]:
    """Run a single sweep over non-terminal video jobs.

    Returns the list of job snapshots after the poll.  Each job is polled
    in its own transaction so a single failure can't poison the rest of
    the batch.  When ``composio`` is omitted, a process-wide client is
    built (and **not** closed — callers reuse the singleton across calls).

    Errors per job are logged and swallowed so the worker can keep
    making progress on the remaining queue.  A top-level error (e.g.
    DB unreachable) propagates so the scheduler marks the run failed.
    """
    factory = get_session_factory()
    own_client = composio is None
    client = composio or build_client()
    polled: list[VideoJobView] = []
    try:
        async with factory() as session:
            service = VideoGenerationService(session, client)
            active = await service.list_active(limit=limit)
        if not active:
            return polled

        for snapshot in active:
            try:
                async with factory() as session:
                    service = VideoGenerationService(session, client)
                    refreshed = await service.poll(snapshot.id)
                    await session.commit()
                polled.append(refreshed)
            except Exception as exc:  # noqa: BLE001 — keep the sweep alive
                logger.warning(
                    "video.poll.job_failed",
                    job_id=snapshot.id,
                    error=str(exc),
                )
                continue
    finally:
        if own_client:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 — best-effort cleanup
                logger.debug("video.poll.client_close_failed", exc_info=True)

    logger.info("video.poll.summary", polled=len(polled))
    return polled


async def run_video_polling_loop(
    *,
    interval_s: float = 10.0,
    limit: int = 100,
    iterations: int | None = None,
) -> None:
    """Long-running variant of :func:`run_video_polling_pass`.

    Sleeps ``interval_s`` seconds between passes.  Pass ``iterations`` to
    bound the loop (tests).  Re-uses a single Composio client across
    passes so the underlying ``httpx.AsyncClient`` pools are warm.
    """
    client = build_client()
    try:
        i = 0
        while True:
            try:
                await run_video_polling_pass(limit=limit, composio=client)
            except Exception:  # noqa: BLE001 — top-level pass failure
                logger.exception("video.poll.pass_failed")
            i += 1
            if iterations is not None and i >= iterations:
                return
            await asyncio.sleep(interval_s)
    finally:
        try:
            await client.aclose()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            logger.debug("video.poll.client_close_failed", exc_info=True)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m app.workers.video_polling",
        description="Poll non-terminal video generation jobs.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run continuously instead of performing one polling pass.",
    )
    parser.add_argument(
        "--interval-s",
        type=float,
        default=10.0,
        help="Seconds between polling passes in --loop mode.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Maximum active jobs to poll per pass.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: ``python -m app.workers.video_polling``.

    Exits 0 on success, 1 if the pass raised — what cron/k8s use to retry.
    """
    args = _parse_args(argv)
    try:
        if args.loop:
            asyncio.run(
                run_video_polling_loop(
                    interval_s=args.interval_s,
                    limit=args.limit,
                )
            )
            return 0
        results = asyncio.run(run_video_polling_pass(limit=args.limit))
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001 — already logged above
        return 1
    print(f"video_jobs_polled={len(results)}")  # noqa: T201 — CLI output
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
