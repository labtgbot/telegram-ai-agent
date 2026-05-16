"""Data types for the Composio MCP client.

These are intentionally framework-free dataclasses so the same shape
travels through tests, mocks and the HTTP implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolInvocation:
    """Inputs that fully describe a single Composio tool call.

    ``user_id`` is the Composio connected-account identifier (falls back
    to ``COMPOSIO_DEFAULT_USER_ID`` at the client layer).  ``service_type``
    is the optional logical name (``text``, ``image``, ``video``,
    ``search``, ``voice``, ``document``) used both for routing and for
    the ``token_usage_logs.service_type`` column.
    """

    tool: str
    params: dict[str, Any]
    service_type: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Outcome of a single Composio invocation.

    The shape mirrors the Composio REST response (`successful`, `data`,
    `error`) plus client-side bookkeeping (`tool`, `attempts`,
    `latency_ms`) so callers can record ``token_usage_logs`` without
    re-deriving the values.
    """

    tool: str
    successful: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    raw: dict[str, Any] | None = None
    attempts: int = 1
    latency_ms: int | None = None
    service_type: str | None = None
    mcp_server: str | None = None


__all__ = ["ToolInvocation", "ToolResult"]
