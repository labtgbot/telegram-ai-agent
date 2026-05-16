"""Bridge between Composio invocations and ``token_usage_logs``.

The token-spending side is owned by :class:`app.services.token_service.TokenService`;
this helper covers the audit-only path (zero-cost calls or post-hoc
logging that doesn't debit the balance — e.g. cache hits, free
toolkits).

For paid calls, prefer ``TokenService.spend(...)`` directly and forward
``composio_tool``, ``mcp_server``, ``processing_time_ms`` and
``response_status`` from the :class:`ToolResult`.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.token_usage_log import TokenUsageLog
from app.services.composio.models import ToolResult

logger = get_logger(__name__)


async def log_invocation(
    session: AsyncSession,
    *,
    user_id: int,
    result: ToolResult,
    tokens_consumed: int = 0,
    request_params: dict[str, Any] | None = None,
) -> TokenUsageLog:
    """Insert an audit row into ``token_usage_logs``.

    The caller is responsible for flushing / committing the transaction —
    this matches the pattern used by every other service in the module.
    ``tokens_consumed`` defaults to ``0`` because the typical paid-path
    already records consumption via :meth:`TokenService.spend`; pass a
    non-zero value only when you want this helper to own both audit and
    accounting.
    """
    entry = TokenUsageLog(
        user_id=user_id,
        service_type=(result.service_type or result.tool)[:100],
        tokens_consumed=int(tokens_consumed),
        request_params=request_params,
        response_status="ok" if result.successful else "error",
        processing_time_ms=result.latency_ms,
        composio_tool=result.tool[:255],
        mcp_server=(result.mcp_server or None) and result.mcp_server[:255],
    )
    session.add(entry)
    await session.flush()
    logger.info(
        "composio.invocation_logged",
        user_id=user_id,
        composio_tool=result.tool,
        service_type=result.service_type,
        attempts=result.attempts,
        latency_ms=result.latency_ms,
        successful=result.successful,
        usage_log_id=entry.id,
    )
    return entry


__all__ = ["log_invocation"]
