"""Subscription renewal worker.

Designed to be invoked once per day by an external scheduler (cron, k8s
CronJob, Celery beat).  Iterates active auto-renew subscriptions whose
``expires_at`` is in the past and:

* credits the next period's tokens via the regular ``TokenService``
  pathway, recording a ``purchase`` transaction marked
  ``payment_id="renewal:<sub_id>:<period_index>"`` for idempotency;
* extends ``expires_at`` by the package's ``subscription_days``;
* refreshes ``users.premium_expires_at`` so the bot UI shows the new
  expiry immediately.

The work itself lives in :func:`app.services.payments.process_subscription_renewals`
— this module is a thin entrypoint that owns the database session.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.services.payments import PaymentResult, process_subscription_renewals

logger = get_logger(__name__)


async def run_subscription_renewals(
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[PaymentResult]:
    """Run a single renewal pass and commit the result.

    Returns the list of renewals that were applied — empty when nothing
    was due.  Errors are logged and re-raised so the scheduler (or test
    harness) can mark the run as failed.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            results = await process_subscription_renewals(
                session, now=now, limit=limit
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("payment.renewal.failed")
            raise
    logger.info("payment.renewal.summary", renewals=len(results))
    return results


def main() -> int:
    """CLI entrypoint: ``python -m app.workers.subscriptions``.

    Exits 0 on success (regardless of how many renewals ran), 1 if the
    task raised — that's what cron/k8s use to retry.
    """
    try:
        results = asyncio.run(run_subscription_renewals())
    except Exception:  # noqa: BLE001 — already logged above
        return 1
    print(f"renewals_applied={len(results)}")  # noqa: T201 — CLI output
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
