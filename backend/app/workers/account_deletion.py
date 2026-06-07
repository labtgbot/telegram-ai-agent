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

from sqlalchemy.exc import SQLAlchemyError

from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.services.account_deletion import (
    anonymise_user,
    list_due_deletions,
    mark_deletion_completed,
    mark_deletion_failed,
)

logger = get_logger(__name__)

MAX_FAILURE_REASON_LEN = 500


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
                request_id = request.id
                user_id = request.user_id
                processed += 1
                try:
                    changed = await anonymise_user(
                        session, user_id=user_id, now=now
                    )
                    await mark_deletion_completed(session, request=request, now=now)
                    await session.commit()
                    if changed:
                        anonymised += 1
                except Exception as exc:
                    await session.rollback()
                    failed += 1
                    failure_reason = _format_failure_reason(exc)
                    await mark_deletion_failed(
                        session,
                        request_id=request_id,
                        failure_reason=failure_reason,
                        now=now,
                    )
                    await session.commit()
                    logger.exception(
                        "account_deletion.failed",
                        user_id=user_id,
                        request_id=request_id,
                        failure_reason=failure_reason,
                    )
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


def _format_failure_reason(exc: Exception) -> str:
    """Return a concise failure reason without serialising SQL statements."""
    if isinstance(exc, SQLAlchemyError):
        original = getattr(exc, "orig", None)
        if original is not None:
            return f"{type(exc).__name__}: {type(original).__name__}"[
                :MAX_FAILURE_REASON_LEN
            ]
        return type(exc).__name__[:MAX_FAILURE_REASON_LEN]

    message = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    if message:
        return f"{type(exc).__name__}: {message}"[:MAX_FAILURE_REASON_LEN]
    return type(exc).__name__[:MAX_FAILURE_REASON_LEN]


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
