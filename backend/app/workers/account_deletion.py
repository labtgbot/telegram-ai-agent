"""Periodic account-deletion worker.

Invoked daily (cron / Kubernetes CronJob) to anonymise users whose
``account_deletion_requests.scheduled_for`` deadline has passed. Designed
to be idempotent: re-running on the same data is safe.

* :func:`process_due_deletions` — programmatic entrypoint usable from
  tests or other tasks.
* :func:`main` — CLI entrypoint (``python -m app.workers.account_deletion``).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.models.account_deletion import DELETION_STATUS_FAILED
from app.services.account_deletion import (
    anonymise_user,
    list_due_deletions,
    mark_deletion_completed,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class DeletionRunResult:
    processed: int
    anonymised: int
    failed: int


async def process_due_deletions(
    *,
    now: datetime | None = None,
    limit: int = 100,
) -> DeletionRunResult:
    """Anonymise every user whose grace period has expired."""
    factory = get_session_factory()
    processed = anonymised = failed = 0
    async with factory() as session:
        try:
            due = await list_due_deletions(session, now=now, limit=limit)
            for request in due:
                processed += 1
                try:
                    changed = await anonymise_user(
                        session, user_id=request.user_id, now=now
                    )
                    await mark_deletion_completed(session, request=request, now=now)
                    if changed:
                        anonymised += 1
                except Exception:
                    failed += 1
                    request.status = DELETION_STATUS_FAILED
                    logger.exception(
                        "account_deletion.failed",
                        user_id=request.user_id,
                        request_id=request.id,
                    )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("account_deletion.run_failed")
            raise
    logger.info(
        "account_deletion.run_summary",
        processed=processed,
        anonymised=anonymised,
        failed=failed,
    )
    return DeletionRunResult(processed=processed, anonymised=anonymised, failed=failed)


def main() -> int:
    try:
        result = asyncio.run(process_due_deletions())
    except Exception:  # noqa: BLE001 — already logged above
        return 1
    print(  # noqa: T201 — CLI summary line
        f"processed={result.processed} "
        f"anonymised={result.anonymised} failed={result.failed}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
