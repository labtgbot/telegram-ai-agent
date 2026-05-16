"""Unit tests for ``app.bot.client.TelegramClient``.

The client is exercised against an in-memory ``httpx`` transport so we can
assert exact request payloads without spinning up a network server.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.bot.client import TelegramApiError, TelegramClient


def _ok(result: object | None = True) -> httpx.Response:
    return httpx.Response(200, json={"ok": True, "result": result})


@pytest.mark.asyncio
async def test_send_message_strips_none_and_returns_result() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        return _ok({"message_id": 7})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = TelegramClient("123:abc", http_client=http)
        result = await client.send_message(42, "hello")

    assert result == {"message_id": 7}
    assert captured["url"].endswith("/bot123:abc/sendMessage")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["chat_id"] == 42
    assert body["text"] == "hello"
    # parse_mode and disable_web_page_preview have defaults — they ARE sent.
    assert body["parse_mode"] == "HTML"
    assert body["disable_web_page_preview"] is True
    # reply_markup is None by default — it should NOT be in the payload.
    assert "reply_markup" not in body


@pytest.mark.asyncio
async def test_call_raises_on_ok_false() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": False, "error_code": 400, "description": "Bad Request"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = TelegramClient("123:abc", http_client=http)
        with pytest.raises(TelegramApiError) as excinfo:
            await client.send_message(1, "x")

    assert excinfo.value.error_code == 400
    assert "Bad Request" in str(excinfo.value)


@pytest.mark.asyncio
async def test_call_raises_on_transport_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = TelegramClient("123:abc", http_client=http)
        with pytest.raises(TelegramApiError):
            await client.send_message(1, "x")


@pytest.mark.asyncio
async def test_set_my_commands_sends_payload() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode())
        captured["url"] = str(request.url)
        return _ok(True)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = TelegramClient("xyz", http_client=http)
        await client.set_my_commands(
            [{"command": "start", "description": "Start"}],
        )

    assert captured["url"].endswith("/setMyCommands")
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["commands"] == [{"command": "start", "description": "Start"}]


def test_constructor_rejects_empty_token() -> None:
    with pytest.raises(ValueError):
        TelegramClient("")
