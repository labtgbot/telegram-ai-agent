"""Periodic cleanup worker for persisted admin refresh-token sessions."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.logging import get_logger
from app.services.admin_refresh_sessions import cleanup_refresh_sessions

logger = get_logger(__name__)


async def run_admin_refresh_session_cleanup(
    *,
    now: datetime | None = None,
) -> int:
    """Run one cleanup pass and commit deleted admin refresh sessions."""
    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        try:
            deleted = await cleanup_refresh_sessions(
                session,
                now=now,
                revoked_retention_seconds=settings.admin_refresh_token_ttl,
            )
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("admin_refresh_sessions.cleanup.failed")
            raise
    logger.info("admin_refresh_sessions.cleanup.summary", deleted=deleted)
    return deleted


def main() -> int:
    try:
        deleted = asyncio.run(run_admin_refresh_session_cleanup())
    except Exception:  # noqa: BLE001 — already logged above
        return 1
    print(f"deleted={deleted}")  # noqa: T201 — CLI summary line
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
