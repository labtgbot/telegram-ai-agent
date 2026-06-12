"""Composio MCP HTTP client.

The client is intentionally thin — Phase 1 only needs the
``invoke(tool, params) -> ToolResult`` surface.  Streaming and provider
tool-discovery are deferred to later phases.

Retry policy
------------
Transient failures (``ComposioTransientError``) are retried up to
``COMPOSIO_MAX_RETRIES`` attempts with exponential backoff:

    delay_n = min(backoff_base * 2 ** (n - 1), backoff_max)

Non-transient errors (``ComposioInvalidToolError``,
:class:`ComposioAuthError`, 4xx other than 408/429) bypass the retry
loop.  ``asyncio.CancelledError`` is propagated immediately so a
cancelled request never blocks on backoff.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Protocol, runtime_checkable

import httpx

from app.core.config import COMPOSIO_MODE_REAL, Settings, get_settings
from app.core.logging import get_logger
from app.services.composio.errors import (
    ComposioAuthError,
    ComposioError,
    ComposioInvalidToolError,
    ComposioTransientError,
)
from app.services.composio.models import ToolInvocation, ToolResult
from app.services.composio.tools import SERVICE_TYPE_TO_TOOL, resolve_tool

logger = get_logger(__name__)


_TRANSIENT_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


@runtime_checkable
class ComposioClient(Protocol):
    """Protocol every Composio client implements.

    Implementations must be safe to share between concurrent coroutines
    (the HTTP client uses a single ``httpx.AsyncClient`` under the
    hood).
    """

    async def invoke(
        self,
        tool: str,
        params: dict[str, Any] | None = None,
        *,
        user_id: str | None = None,
        service_type: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult: ...

    async def invoke_for_service(
        self,
        service_type: str,
        params: dict[str, Any] | None = None,
        *,
        user_id: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        overrides: dict[str, str] | None = None,
    ) -> ToolResult: ...

    async def aclose(self) -> None: ...


class HttpComposioClient:
    """Composio MCP client backed by ``httpx.AsyncClient``."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        default_user_id: str = "",
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        backoff_max: float = 8.0,
        http_client: httpx.AsyncClient | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        if not api_key:
            raise ComposioAuthError("COMPOSIO_API_KEY is required for HttpComposioClient")
        self._api_key = api_key
        self._default_user_id = default_user_id
        self._max_retries = max(int(max_retries), 1)
        self._backoff_base = max(float(backoff_base), 0.0)
        self._backoff_max = max(float(backoff_max), 0.0)
        self._sleep = sleep
        self._owns_client = http_client is None
        self._http: httpx.AsyncClient = http_client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
        )
        self._headers = {
            "X-API-Key": api_key,
            "Accept": "application/json",
            "User-Agent": "telegram-ai-agent-backend/0.1",
        }

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> HttpComposioClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

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
        """Resolve ``service_type`` and call :meth:`invoke`."""
        tool = resolve_tool(service_type, overrides=overrides)
        return await self.invoke(
            tool,
            params or {},
            user_id=user_id,
            service_type=service_type,
            request_id=request_id,
            metadata=metadata,
        )

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
            user_id=user_id or self._default_user_id or None,
            request_id=request_id,
            metadata=dict(metadata or {}),
        )

        last_error: Exception | None = None
        started = time.monotonic()
        for attempt in range(1, self._max_retries + 1):
            try:
                response = await self._http.post(
                    "/api/v3/tools/execute",
                    json=self._build_payload(invocation),
                    headers=self._headers,
                )
            except httpx.TimeoutException as exc:
                last_error = ComposioTransientError(
                    f"composio request timed out: {exc}", attempts=attempt
                )
            except httpx.HTTPError as exc:
                last_error = ComposioTransientError(
                    f"composio network error: {exc}", attempts=attempt
                )
            else:
                if response.status_code in _TRANSIENT_STATUS:
                    last_error = ComposioTransientError(
                        f"composio returned {response.status_code}",
                        attempts=attempt,
                    )
                elif response.status_code in (401, 403):
                    raise ComposioAuthError(
                        f"composio auth failed: {response.status_code} {response.text[:200]}"
                    )
                elif response.status_code >= 400:
                    raise ComposioError(
                        f"composio error {response.status_code}: {response.text[:200]}"
                    )
                else:
                    return self._make_result(
                        invocation,
                        response,
                        attempts=attempt,
                        started=started,
                    )

            if attempt >= self._max_retries:
                break
            await self._sleep(self._backoff_delay(attempt))

        assert last_error is not None
        if isinstance(last_error, ComposioTransientError):
            last_error.attempts = self._max_retries
        raise last_error

    def _build_payload(self, invocation: ToolInvocation) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool": invocation.tool,
            "arguments": invocation.params,
        }
        if invocation.user_id:
            payload["user_id"] = invocation.user_id
        if invocation.request_id:
            payload["request_id"] = invocation.request_id
        if invocation.metadata:
            payload["metadata"] = invocation.metadata
        return payload

    def _make_result(
        self,
        invocation: ToolInvocation,
        response: httpx.Response,
        *,
        attempts: int,
        started: float,
    ) -> ToolResult:
        try:
            body: dict[str, Any] = response.json()
        except ValueError:
            body = {"raw": response.text}
        successful = bool(body.get("successful", True))
        return ToolResult(
            tool=invocation.tool,
            successful=successful,
            data=body.get("data") or {},
            error=body.get("error"),
            raw=body,
            attempts=attempts,
            latency_ms=int((time.monotonic() - started) * 1000),
            service_type=invocation.service_type,
            mcp_server=body.get("mcp_server") or response.headers.get("x-mcp-server"),
        )

    def _backoff_delay(self, attempt: int) -> float:
        delay = self._backoff_base * (2 ** (attempt - 1))
        return min(delay, self._backoff_max)


def _build_mock_client(cfg: Settings) -> ComposioClient:
    from app.services.composio.mock import MockComposioClient

    client = MockComposioClient(default_user_id=cfg.composio_default_user_id or None)
    # Load-test hook: when COMPOSIO_MOCK_TEXT_RESPONSE is set, the mock
    # returns a text payload the generation pipeline can extract instead
    # of the default {"echo": params} stub. Lets locust drive the full
    # /generate/text happy path without a real provider.
    mock_text = os.environ.get("COMPOSIO_MOCK_TEXT_RESPONSE", "").strip()
    if mock_text:
        for tool in {SERVICE_TYPE_TO_TOOL["text"], SERVICE_TYPE_TO_TOOL["chat"]}:
            client.set_response(tool, data={"text": mock_text})
    return client


def build_client(settings: Settings | None = None) -> ComposioClient:
    """Factory: build the configured Composio client.

    ``COMPOSIO_MODE=real`` requires ``COMPOSIO_API_KEY`` and returns the HTTP
    client. ``COMPOSIO_MODE=mock`` returns the in-memory mock only for explicit
    non-production environments.
    """
    cfg = settings or get_settings()
    mode = cfg.composio_mode_normalized
    if cfg.composio_mock_enabled:
        if not cfg.is_non_production:
            raise ComposioAuthError(
                "COMPOSIO_MODE=mock is only allowed when APP_ENV is development, "
                "dev, local, test, or ci"
            )
        logger.info("composio.using_mock", reason="explicit_mock_mode")
        return _build_mock_client(cfg)
    if mode != COMPOSIO_MODE_REAL:
        raise ComposioError("COMPOSIO_MODE must be either 'real' or 'mock'")
    if not cfg.composio_enabled:
        raise ComposioAuthError("COMPOSIO_API_KEY is required when COMPOSIO_MODE=real")
    return HttpComposioClient(
        api_key=cfg.composio_api_key,
        base_url=cfg.composio_base_url,
        default_user_id=cfg.composio_default_user_id,
        timeout=cfg.composio_timeout_seconds,
        max_retries=cfg.composio_max_retries,
        backoff_base=cfg.composio_backoff_base_seconds,
        backoff_max=cfg.composio_backoff_max_seconds,
    )


__all__ = ["ComposioClient", "HttpComposioClient", "build_client"]
