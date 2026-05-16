"""In-memory Composio client used by tests and local dev.

The mock implements the same :class:`ComposioClient` protocol as the
HTTP client.  Callers can either pre-load deterministic responses
(`set_response`) or supply a callable handler (`set_handler`) for
dynamic behaviour.  Every invocation is recorded in ``calls`` so tests
can assert on the request flow without monkey-patching.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.services.composio.errors import (
    ComposioError,
    ComposioInvalidToolError,
)
from app.services.composio.models import ToolInvocation, ToolResult
from app.services.composio.tools import resolve_tool

Handler = Callable[[ToolInvocation], Awaitable[ToolResult] | ToolResult]


class MockComposioClient:
    """Deterministic Composio client for tests.

    Examples
    --------
    >>> client = MockComposioClient()
    >>> client.set_response("gemini", data={"text": "hi"})
    >>> result = await client.invoke("gemini", {"prompt": "..."})
    >>> assert result.successful and result.data["text"] == "hi"
    """

    def __init__(self, *, default_user_id: str | None = None) -> None:
        self._default_user_id = default_user_id
        self._responses: dict[str, ToolResult] = {}
        self._handlers: dict[str, Handler] = {}
        self.calls: list[ToolInvocation] = []
        self.closed: bool = False

    # --------------------------------------------------------- configuration

    def set_response(
        self,
        tool: str,
        *,
        data: dict[str, Any] | None = None,
        successful: bool = True,
        error: str | None = None,
        mcp_server: str | None = None,
    ) -> None:
        """Register a static response for ``tool``."""
        self._responses[tool] = ToolResult(
            tool=tool,
            successful=successful,
            data=dict(data or {}),
            error=error,
            mcp_server=mcp_server,
        )

    def set_handler(self, tool: str, handler: Handler) -> None:
        """Register a callable handler — overrides ``set_response`` for ``tool``."""
        self._handlers[tool] = handler

    def set_error(self, tool: str, exc: BaseException) -> None:
        """Configure the mock to raise ``exc`` whenever ``tool`` is invoked."""

        async def _raise(_: ToolInvocation) -> ToolResult:
            raise exc

        self._handlers[tool] = _raise

    def reset(self) -> None:
        self._responses.clear()
        self._handlers.clear()
        self.calls.clear()
        self.closed = False

    # ----------------------------------------------------------------- API

    async def invoke(
        self,
        tool: str,
        params: dict[str, Any] | None = None,
        *,
        user_id: str | None = None,
        service_type: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        if not tool or not tool.strip():
            raise ComposioInvalidToolError("tool is required")
        invocation = ToolInvocation(
            tool=tool.strip(),
            params=dict(params or {}),
            service_type=service_type,
            user_id=user_id or self._default_user_id,
            request_id=request_id,
            metadata=dict(metadata or {}),
        )
        self.calls.append(invocation)

        started = time.monotonic()
        handler = self._handlers.get(invocation.tool)
        if handler is not None:
            outcome = handler(invocation)
            if hasattr(outcome, "__await__"):
                outcome = await outcome  # type: ignore[assignment]
            if not isinstance(outcome, ToolResult):  # pragma: no cover - defensive
                raise ComposioError("mock handler must return a ToolResult")
            return self._stamp(outcome, invocation, started)

        if invocation.tool in self._responses:
            return self._stamp(self._responses[invocation.tool], invocation, started)

        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data={"echo": invocation.params},
            service_type=invocation.service_type,
            attempts=1,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    async def invoke_for_service(
        self,
        service_type: str,
        params: dict[str, Any] | None = None,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        overrides: dict[str, str] | None = None,
    ) -> ToolResult:
        tool = resolve_tool(service_type, overrides=overrides)
        return await self.invoke(
            tool,
            params or {},
            user_id=user_id,
            service_type=service_type,
            request_id=request_id,
            metadata=metadata,
        )

    async def aclose(self) -> None:
        self.closed = True

    # -------------------------------------------------------------- helpers

    @staticmethod
    def _stamp(
        result: ToolResult,
        invocation: ToolInvocation,
        started: float,
    ) -> ToolResult:
        """Stamp latency / attempt metadata on a stored response."""
        return ToolResult(
            tool=invocation.tool,
            successful=result.successful,
            data=dict(result.data),
            error=result.error,
            raw=result.raw,
            attempts=1,
            latency_ms=int((time.monotonic() - started) * 1000),
            service_type=invocation.service_type or result.service_type,
            mcp_server=result.mcp_server,
        )


__all__ = ["MockComposioClient"]
