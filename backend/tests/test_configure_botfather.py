"""Unit tests for ``scripts/configure_botfather.py``.

The script talks to the Bot API via ``TelegramClient``; we exercise it
against an ``httpx.MockTransport`` to capture the exact methods + payloads
that get applied, without ever leaving the test process.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import configure_botfather  # noqa: E402
from scripts.configure_botfather import BotFatherConfig, apply  # noqa: E402


def _transport(
    handler: Callable[[str, dict[str, object]], httpx.Response],
) -> httpx.MockTransport:
    """Build a mock transport that records each Bot API method invocation."""

    async def _handle(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content.decode() or "{}")
        return handler(method, body)

    return httpx.MockTransport(_handle)


@pytest.mark.asyncio
async def test_apply_calls_all_botfather_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    def handler(method: str, body: dict[str, object]) -> httpx.Response:
        calls.append((method, body))
        if method == "getMe":
            return httpx.Response(
                200, json={"ok": True, "result": {"username": "prod_bot"}}
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = _transport(handler)
    http = httpx.AsyncClient(transport=transport)

    # Patch TelegramClient construction so the script uses our HTTP transport.
    original = configure_botfather.TelegramClient

    def factory(token: str) -> configure_botfather.TelegramClient:
        return original(token, http_client=http)

    monkeypatch.setattr(configure_botfather, "TelegramClient", factory)

    config = BotFatherConfig(
        bot_token="123:abc",
        mini_app_url="https://app.example.com",
        expected_username="prod_bot",
        language_codes=("", "ru"),
        dry_run=False,
    )

    await apply(config)
    await http.aclose()

    methods = [m for m, _ in calls]
    assert methods.count("getMe") == 1
    # Per language: setMyCommands + setMyDescription + setMyShortDescription = 3
    # Two languages -> 6 calls.
    assert methods.count("setMyCommands") == 2
    assert methods.count("setMyDescription") == 2
    assert methods.count("setMyShortDescription") == 2
    assert methods.count("setChatMenuButton") == 1

    menu = next(body for m, body in calls if m == "setChatMenuButton")
    assert menu["menu_button"] == {
        "type": "web_app",
        "text": configure_botfather.MENU_BUTTON_TEXT,
        "web_app": {"url": "https://app.example.com"},
    }

    # Default-language call must omit ``language_code`` (the API rejects "").
    default_cmd = next(
        body
        for m, body in calls
        if m == "setMyCommands" and "language_code" not in body
    )
    assert default_cmd["commands"], "command list must not be empty"


@pytest.mark.asyncio
async def test_apply_rejects_mismatched_username(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(method: str, body: dict[str, object]) -> httpx.Response:
        if method == "getMe":
            return httpx.Response(
                200, json={"ok": True, "result": {"username": "wrong_bot"}}
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = _transport(handler)
    http = httpx.AsyncClient(transport=transport)

    original = configure_botfather.TelegramClient

    def factory(token: str) -> configure_botfather.TelegramClient:
        return original(token, http_client=http)

    monkeypatch.setattr(configure_botfather, "TelegramClient", factory)

    config = BotFatherConfig(
        bot_token="123:abc",
        mini_app_url="https://app.example.com",
        expected_username="prod_bot",
        language_codes=("",),
        dry_run=False,
    )

    with pytest.raises(SystemExit, match="Refusing to update"):
        await apply(config)
    await http.aclose()


@pytest.mark.asyncio
async def test_dry_run_makes_no_api_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def handler(method: str, body: dict[str, object]) -> httpx.Response:
        calls.append(method)
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = _transport(handler)
    http = httpx.AsyncClient(transport=transport)

    original = configure_botfather.TelegramClient

    def factory(token: str) -> configure_botfather.TelegramClient:
        return original(token, http_client=http)

    monkeypatch.setattr(configure_botfather, "TelegramClient", factory)

    config = BotFatherConfig(
        bot_token="123:abc",
        mini_app_url="https://app.example.com",
        expected_username=None,
        language_codes=("",),
        dry_run=True,
    )

    await apply(config)
    await http.aclose()
    assert calls == []


def test_from_env_validates_mini_app_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_MINI_APP_URL", "http://insecure.example.com")
    monkeypatch.delenv("TELEGRAM_BOT_USERNAME", raising=False)
    monkeypatch.delenv("TELEGRAM_BOTFATHER_DRY_RUN", raising=False)
    monkeypatch.delenv("TELEGRAM_BOTFATHER_LANGUAGE_CODES", raising=False)
    with pytest.raises(SystemExit, match="https://"):
        BotFatherConfig.from_env()


def test_from_env_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_MINI_APP_URL", "https://example.com")
    with pytest.raises(SystemExit, match="TELEGRAM_BOT_TOKEN"):
        BotFatherConfig.from_env()


def test_from_env_defaults_language_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_MINI_APP_URL", "https://example.com")
    monkeypatch.delenv("TELEGRAM_BOTFATHER_LANGUAGE_CODES", raising=False)
    config = BotFatherConfig.from_env()
    assert config.language_codes == configure_botfather.DEFAULT_LANGUAGE_CODES


def test_apply_can_run_under_asyncio_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """``configure_botfather.main`` should be safe to invoke from a script."""

    def handler(method: str, body: dict[str, object]) -> httpx.Response:
        if method == "getMe":
            return httpx.Response(
                200, json={"ok": True, "result": {"username": "prod_bot"}}
            )
        return httpx.Response(200, json={"ok": True, "result": True})

    transport = _transport(handler)
    http = httpx.AsyncClient(transport=transport)

    original = configure_botfather.TelegramClient

    def factory(token: str) -> configure_botfather.TelegramClient:
        return original(token, http_client=http)

    monkeypatch.setattr(configure_botfather, "TelegramClient", factory)

    config = BotFatherConfig(
        bot_token="123:abc",
        mini_app_url="https://app.example.com",
        expected_username="prod_bot",
        language_codes=("",),
        dry_run=False,
    )
    asyncio.run(apply(config))
    asyncio.run(http.aclose())
