"""Unit tests for the Composio MCP client.

The HTTP client is exercised against ``httpx.MockTransport`` so we can
assert payload shape and retry behaviour without hitting the network.
The mock client and tool resolver have their own pure-Python coverage.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from app.services.composio import (
    SERVICE_TYPE_TO_TOOL,
    ComposioAuthError,
    ComposioError,
    ComposioInvalidToolError,
    ComposioTransientError,
    HttpComposioClient,
    MockComposioClient,
    ToolResult,
    build_client,
    resolve_tool,
)


def _make_http_client(
    handler: Any,
    *,
    max_retries: int = 3,
    backoff_base: float = 0.0,
    backoff_max: float = 0.0,
    sleeps: list[float] | None = None,
) -> HttpComposioClient:
    """Build an :class:`HttpComposioClient` wired to ``handler`` via MockTransport."""
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="https://composio.test")

    async def fake_sleep(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)
        await asyncio.sleep(0)

    return HttpComposioClient(
        api_key="test-key",
        base_url="https://composio.test",
        default_user_id="default-user",
        max_retries=max_retries,
        backoff_base=backoff_base,
        backoff_max=backoff_max,
        http_client=http,
        sleep=fake_sleep,
    )


# --------------------------------------------------------------- resolve_tool


@pytest.mark.parametrize(
    "service_type,expected",
    [
        ("text", "gemini"),
        ("chat", "gemini"),
        ("search", "composio_search"),
        ("image", "image_gen"),
        ("video", "video_gen"),
        ("Voice", "elevenlabs"),
        ("DOCUMENT", "document_parser"),
    ],
)
def test_resolve_tool_known_service_types(service_type: str, expected: str) -> None:
    assert resolve_tool(service_type) == expected


def test_resolve_tool_overrides_take_priority() -> None:
    assert resolve_tool("text", overrides={"text": "claude"}) == "claude"


def test_resolve_tool_unknown_service_type_raises() -> None:
    with pytest.raises(ComposioInvalidToolError):
        resolve_tool("???")


def test_resolve_tool_empty_service_type_raises() -> None:
    with pytest.raises(ComposioInvalidToolError):
        resolve_tool("")


def test_service_type_mapping_covers_required_toolkits() -> None:
    """Acceptance criteria: toolkits enumerated by config."""
    required = {"gemini", "composio_search", "image_gen", "video_gen"}
    assert required.issubset(set(SERVICE_TYPE_TO_TOOL.values()))


# ----------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_invoke_returns_tool_result_with_payload() -> None:
    captured: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "successful": True,
                "data": {"text": "hello"},
                "mcp_server": "composio-prod-1",
            },
        )

    client = _make_http_client(handler)
    try:
        result = await client.invoke(
            "gemini",
            {"prompt": "hi"},
            service_type="text",
            request_id="req-1",
        )
    finally:
        await client.aclose()

    assert result.tool == "gemini"
    assert result.successful is True
    assert result.data == {"text": "hello"}
    assert result.service_type == "text"
    assert result.mcp_server == "composio-prod-1"
    assert result.attempts == 1
    assert result.latency_ms is not None and result.latency_ms >= 0

    assert captured["url"].endswith("/api/v3/tools/execute")
    assert captured["body"]["tool"] == "gemini"
    assert captured["body"]["arguments"] == {"prompt": "hi"}
    assert captured["body"]["user_id"] == "default-user"
    assert captured["body"]["request_id"] == "req-1"
    assert captured["headers"].get("x-api-key") == "test-key"


@pytest.mark.asyncio
async def test_invoke_for_service_resolves_tool() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert body["tool"] == "composio_search"
        return httpx.Response(200, json={"successful": True, "data": {"hits": 3}})

    client = _make_http_client(handler)
    try:
        result = await client.invoke_for_service("search", {"q": "fastapi"})
    finally:
        await client.aclose()

    assert result.tool == "composio_search"
    assert result.service_type == "search"
    assert result.data == {"hits": 3}


# ---------------------------------------------------------------------- retry


@pytest.mark.asyncio
async def test_invoke_retries_on_transient_status_then_succeeds() -> None:
    calls: list[int] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, json={"successful": True, "data": {"ok": True}})

    sleeps: list[float] = []
    client = _make_http_client(
        handler,
        max_retries=3,
        backoff_base=0.25,
        backoff_max=4.0,
        sleeps=sleeps,
    )
    try:
        result = await client.invoke("gemini", {"prompt": "x"})
    finally:
        await client.aclose()

    assert len(calls) == 3
    assert result.attempts == 3
    assert result.successful is True
    assert sleeps == [0.25, 0.5]  # exponential growth, two delays for three attempts


@pytest.mark.asyncio
async def test_invoke_gives_up_after_max_retries_on_transient_failures() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    sleeps: list[float] = []
    client = _make_http_client(
        handler, max_retries=3, backoff_base=0.1, backoff_max=1.0, sleeps=sleeps
    )
    try:
        with pytest.raises(ComposioTransientError) as exc:
            await client.invoke("gemini", {"prompt": "x"})
    finally:
        await client.aclose()

    assert exc.value.attempts == 3
    assert len(sleeps) == 2  # max_retries - 1


@pytest.mark.asyncio
async def test_invoke_retries_on_network_error() -> None:
    calls: list[int] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"successful": True, "data": {"ok": True}})

    client = _make_http_client(handler, max_retries=3, backoff_base=0.0)
    try:
        result = await client.invoke("gemini", {})
    finally:
        await client.aclose()

    assert len(calls) == 2
    assert result.attempts == 2


@pytest.mark.asyncio
async def test_invoke_does_not_retry_on_auth_error() -> None:
    calls: list[int] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(401, text="unauthorized")

    client = _make_http_client(handler, max_retries=3)
    try:
        with pytest.raises(ComposioAuthError):
            await client.invoke("gemini", {})
    finally:
        await client.aclose()

    assert calls == [1]


@pytest.mark.asyncio
async def test_invoke_does_not_retry_on_client_error() -> None:
    calls: list[int] = []

    async def handler(_: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(422, text="invalid")

    client = _make_http_client(handler, max_retries=3)
    try:
        with pytest.raises(ComposioError) as exc:
            await client.invoke("gemini", {})
    finally:
        await client.aclose()

    assert not isinstance(exc.value, ComposioAuthError)
    assert calls == [1]


@pytest.mark.asyncio
async def test_backoff_is_capped_to_max() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    sleeps: list[float] = []
    client = _make_http_client(
        handler,
        max_retries=4,
        backoff_base=10.0,
        backoff_max=1.0,
        sleeps=sleeps,
    )
    try:
        with pytest.raises(ComposioTransientError):
            await client.invoke("gemini", {})
    finally:
        await client.aclose()

    assert sleeps == [1.0, 1.0, 1.0]
    for s in sleeps:
        assert s <= 1.0


# ----------------------------------------------------------------- validation


@pytest.mark.asyncio
async def test_invoke_rejects_empty_tool_name() -> None:
    client = _make_http_client(lambda r: httpx.Response(200, json={"successful": True}))
    try:
        with pytest.raises(ComposioInvalidToolError):
            await client.invoke("", {})
    finally:
        await client.aclose()


def test_constructor_rejects_missing_api_key() -> None:
    with pytest.raises(ComposioAuthError):
        HttpComposioClient(api_key="", base_url="https://x")


# --------------------------------------------------------------- mock client


@pytest.mark.asyncio
async def test_mock_client_returns_configured_response() -> None:
    client = MockComposioClient()
    client.set_response("gemini", data={"text": "ok"})
    result = await client.invoke("gemini", {"prompt": "hi"}, service_type="text")
    assert result.successful is True
    assert result.data == {"text": "ok"}
    assert result.service_type == "text"
    assert len(client.calls) == 1
    assert client.calls[0].tool == "gemini"
    assert client.calls[0].params == {"prompt": "hi"}


@pytest.mark.asyncio
async def test_mock_client_handler_overrides_response() -> None:
    client = MockComposioClient()
    client.set_response("gemini", data={"text": "static"})

    async def dynamic(invocation: Any) -> ToolResult:
        return ToolResult(
            tool=invocation.tool,
            successful=True,
            data={"echo": invocation.params},
        )

    client.set_handler("gemini", dynamic)
    result = await client.invoke("gemini", {"prompt": "hi"})
    assert result.data == {"echo": {"prompt": "hi"}}


@pytest.mark.asyncio
async def test_mock_client_raises_configured_error() -> None:
    client = MockComposioClient()
    client.set_error("gemini", ComposioTransientError("boom"))
    with pytest.raises(ComposioTransientError):
        await client.invoke("gemini", {})


@pytest.mark.asyncio
async def test_mock_client_invoke_for_service_resolves_tool() -> None:
    client = MockComposioClient()
    client.set_response("image_gen", data={"url": "https://img.test/a.png"})
    result = await client.invoke_for_service("image", {"prompt": "cat"})
    assert result.tool == "image_gen"
    assert result.service_type == "image"
    assert result.data["url"].startswith("https://")


@pytest.mark.asyncio
async def test_mock_client_default_echo_response() -> None:
    client = MockComposioClient()
    result = await client.invoke("some-tool", {"hello": "world"})
    assert result.successful is True
    assert result.data == {"echo": {"hello": "world"}}


@pytest.mark.asyncio
async def test_mock_client_aclose_marks_closed() -> None:
    client = MockComposioClient()
    await client.aclose()
    assert client.closed is True


# ------------------------------------------------------------- build_client


def test_build_client_returns_mock_when_api_key_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("COMPOSIO_API_KEY", raising=False)
    monkeypatch.setenv("COMPOSIO_API_KEY", "")

    import importlib

    import app.core.config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    client = build_client(config_module.get_settings())
    assert isinstance(client, MockComposioClient)


@pytest.mark.asyncio
async def test_build_client_returns_http_when_api_key_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPOSIO_API_KEY", "secret")
    monkeypatch.setenv("COMPOSIO_DEFAULT_USER_ID", "user-1")

    import importlib

    import app.core.config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()

    client = build_client(config_module.get_settings())
    try:
        assert isinstance(client, HttpComposioClient)
    finally:
        await client.aclose()


# ------------------------------------------------------------- settings prop


def test_settings_composio_toolkits_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "COMPOSIO_DEFAULT_TOOLKITS",
        "gemini, composio_search ,image_gen, video_gen",
    )
    import importlib

    import app.core.config as config_module

    importlib.reload(config_module)
    config_module.get_settings.cache_clear()
    settings = config_module.get_settings()
    assert settings.composio_toolkits == (
        "gemini",
        "composio_search",
        "image_gen",
        "video_gen",
    )
    assert settings.composio_enabled is False  # no API key in this test
