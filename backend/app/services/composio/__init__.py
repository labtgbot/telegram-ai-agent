"""Composio MCP integration — single gateway to AI providers and tools.

The package exposes one protocol — :class:`ComposioClient` — backed by
two implementations:

* :class:`HttpComposioClient` — talks to the Composio MCP REST API over
  ``httpx``;
* :class:`MockComposioClient` — in-memory client used by tests and when
  ``COMPOSIO_API_KEY`` is empty.

See ``docs/architecture/adr/0002-composio-mcp-vs-direct-sdk.md`` for the
why and ``backend/tests/test_composio_client.py`` for behavioural
contract.
"""

from __future__ import annotations

from app.services.composio.client import (
    ComposioClient,
    HttpComposioClient,
    build_client,
)
from app.services.composio.errors import (
    ComposioAuthError,
    ComposioError,
    ComposioInvalidToolError,
    ComposioTransientError,
)
from app.services.composio.mock import MockComposioClient
from app.services.composio.models import ToolInvocation, ToolResult
from app.services.composio.tools import (
    SERVICE_TYPE_TO_TOOL,
    SUPPORTED_TOOLKITS,
    resolve_tool,
)
from app.services.composio.usage import log_invocation

__all__ = [
    "SERVICE_TYPE_TO_TOOL",
    "SUPPORTED_TOOLKITS",
    "ComposioAuthError",
    "ComposioClient",
    "ComposioError",
    "ComposioInvalidToolError",
    "ComposioTransientError",
    "HttpComposioClient",
    "MockComposioClient",
    "ToolInvocation",
    "ToolResult",
    "build_client",
    "log_invocation",
    "resolve_tool",
]
