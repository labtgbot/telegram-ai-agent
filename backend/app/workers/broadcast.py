"""Broadcast delivery worker (Phase 3, issue #28).

Drains the ``broadcast_recipients`` queue for every active campaign while
respecting Telegram's 30 msg/sec ceiling.  The heavy lifting lives in
:mod:`app.services.broadcast` — this module only owns the database
session, Telegram client lifecycle, and the outer loop that picks the
next due broadcast.

Run modes:

* ``python -m app.workers.broadcast`` — one pass: process every due
  broadcast then exit.  Suitable for cron / k8s ``CronJob`` invocations
  every 30s while a campaign is in flight.
* ``python -m app.workers.broadcast --loop`` — long-running mode that
  re-polls every ``BROADCAST_POLL_INTERVAL`` seconds.  Use this when
  Celery beat is not yet wired up (Phase 4).
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime

from app.bot.client import TelegramClient
from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.services.broadcast import (
    TELEGRAM_BROADCAST_RATE_LIMIT,
    drain_broadcast,
    list_due_broadcasts,
)

logger = get_logger(__name__)

# Seconds between polls when running in --loop mode.
BROADCAST_POLL_INTERVAL = 5.0

# Max number of broadcasts a single pass touches.
BROADCAST_MAX_PER_PASS = 5


async def run_broadcast_pass(
    *,
    client: TelegramClient | None = None,
    rate_limit: int = TELEGRAM_BROADCAST_RATE_LIMIT,
    max_broadcasts: int = BROADCAST_MAX_PER_PASS,
    now: datetime | None = None,
) -> int:
    """Process every due broadcast in a single pass.

    Returns the number of broadcasts touched.  When ``client`` is ``None``
    a fresh :class:`TelegramClient` is created from settings and closed
    before the function returns — so unit tests can pass in a fake.
    """
    factory = get_session_factory()
    owned_client = False
    if client is None:
        settings = get_settings()
        if not settings.telegram_bot_token:
            logger.warning("broadcast.worker.no_bot_token")
            return 0
        client = TelegramClient(
            settings.telegram_bot_token,
            base_url=settings.telegram_api_base_url,
        )
        owned_client = True

    touched = 0
    try:
        async with factory() as session:
            due = await list_due_broadcasts(session, now=now, limit=max_broadcasts)
            logger.info("broadcast.worker.pass_start", due=len(due))
            for broadcast in due:
                try:
                    await drain_broadcast(
                        session,
                        client,
                        broadcast=broadcast,
                        rate_limit=rate_limit,
                    )
                    touched += 1
                except Exception:  # noqa: BLE001 — logged for ops visibility
                    logger.exception(
                        "broadcast.worker.drain_failed",
                        broadcast_id=broadcast.id,
                    )
                    await session.rollback()
    finally:
        if owned_client:
            await client.aclose()

    logger.info("broadcast.worker.pass_done", touched=touched)
    return touched


async def run_broadcast_loop(
    *,
    interval: float = BROADCAST_POLL_INTERVAL,
    rate_limit: int = TELEGRAM_BROADCAST_RATE_LIMIT,
) -> None:
    """Long-running variant: poll forever until the process is signalled."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.warning("broadcast.worker.no_bot_token")
        return
    client = TelegramClient(
        settings.telegram_bot_token,
        base_url=settings.telegram_api_base_url,
    )
    try:
        while True:
            await run_broadcast_pass(
                client=client,
                rate_limit=rate_limit,
                now=datetime.now(UTC),
            )
            await asyncio.sleep(interval)
    finally:
        await client.aclose()


def main() -> int:
    """CLI entrypoint: ``python -m app.workers.broadcast``."""
    parser = argparse.ArgumentParser(
        prog="app.workers.broadcast",
        description="Drain due broadcast campaigns via the Telegram Bot API.",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Re-poll every BROADCAST_POLL_INTERVAL seconds (cron-less mode)",
    )
    parser.add_argument(
        "--rate-limit",
        type=int,
        default=TELEGRAM_BROADCAST_RATE_LIMIT,
        help="Maximum messages per second (default: %(default)s)",
    )
    args = parser.parse_args()

    try:
        if args.loop:
            asyncio.run(run_broadcast_loop(rate_limit=args.rate_limit))
            touched = 0
        else:
            touched = asyncio.run(run_broadcast_pass(rate_limit=args.rate_limit))
    except KeyboardInterrupt:
        return 0
    except Exception:  # noqa: BLE001 — already logged in run_*
        return 1

    print(f"broadcasts_processed={touched}")  # noqa: T201 — CLI output
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
