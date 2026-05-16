"""Unit tests for command extraction and the dispatcher's routing.

We mock the :class:`TelegramClient` entirely and use a tiny in-memory store
for the "DB session" so we can verify which command was triggered and what
the bot tried to send back to the user.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.bot.dispatcher import _extract_command, dispatch_update


@dataclass
class _Settings:
    telegram_bot_token: str = "TEST:TOKEN"
    telegram_bot_username: str = "test_bot"
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_webhook_secret: str = ""
    telegram_mini_app_url: str = ""
    telegram_signup_bonus_tokens: int = 50
    telegram_init_data_max_age: int = 86400
    telegram_set_commands_on_startup: bool = False
    admin_super_telegram_ids: str = ""
    super_admin_ids: set[int] = field(default_factory=set)


@pytest.fixture
def settings() -> _Settings:
    return _Settings()


@pytest.fixture
def session_stub() -> AsyncMock:
    """Sessions are pure mocks — handlers we exercise stub their own DB I/O."""
    session = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def client_stub() -> AsyncMock:
    client = AsyncMock()
    client.send_message = AsyncMock(return_value={"message_id": 1})
    client.answer_callback_query = AsyncMock(return_value=True)
    return client


# ----------------------------------------------------------- _extract_command


def test_extract_command_strips_slash_and_lowercases() -> None:
    assert _extract_command("/Start", bot_username="bot") == "start"
    assert _extract_command("/balance 12", bot_username="bot") == "balance"


def test_extract_command_respects_mention() -> None:
    assert _extract_command("/start@test_bot", bot_username="test_bot") == "start"
    assert _extract_command("/start@OTHER", bot_username="test_bot") is None


def test_extract_command_returns_none_for_text() -> None:
    assert _extract_command("hello", bot_username="bot") is None
    assert _extract_command(None, bot_username="bot") is None


# --------------------------------------------------- dispatch routing (mocks)


@pytest.mark.asyncio
async def test_dispatch_routes_unknown_command(
    settings, session_stub, client_stub, monkeypatch
) -> None:
    update = {
        "update_id": 1,
        "message": {
            "chat": {"id": 99},
            "from": {"id": 7, "first_name": "X"},
            "text": "/something_bogus",
        },
    }
    await dispatch_update(
        update,
        settings=settings,
        client=client_stub,
        session=session_stub,
    )
    args, kwargs = client_stub.send_message.await_args
    assert args[0] == 99
    assert "Unknown command" in args[1]


@pytest.mark.asyncio
async def test_dispatch_routes_free_text_to_ask(
    settings, session_stub, client_stub, monkeypatch
) -> None:
    """Non-empty free-form text is rewritten to ``/ask`` and delegated."""
    from app.bot import dispatcher as dispatcher_module

    called: list[dict[str, Any]] = []

    async def fake_ask(ctx):  # type: ignore[no-untyped-def]
        # Record the synthesised message so we can verify the prompt
        # made it through unchanged.
        called.append(dict(ctx.message or {}))

    monkeypatch.setattr(dispatcher_module, "handle_ask", fake_ask)

    update = {
        "update_id": 2,
        "message": {
            "chat": {"id": 5},
            "from": {"id": 7},
            "text": "hello bot",
        },
    }
    await dispatch_update(
        update,
        settings=settings,
        client=client_stub,
        session=session_stub,
    )
    assert called, "handle_ask was not invoked for free-form text"
    assert called[0]["text"] == "/ask hello bot"
    # No direct send_message — the synthetic /ask handler owns the reply.
    client_stub.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_empty_free_text_prompts_help(
    settings, session_stub, client_stub
) -> None:
    """Blank free-form text falls through to a help hint, not to /ask."""
    update = {
        "update_id": 6,
        "message": {
            "chat": {"id": 5},
            "from": {"id": 7},
            "text": "   ",
        },
    }
    await dispatch_update(
        update,
        settings=settings,
        client=client_stub,
        session=session_stub,
    )
    args, _ = client_stub.send_message.await_args
    assert args[0] == 5
    assert "/help" in args[1]


@pytest.mark.asyncio
async def test_dispatch_ignores_updates_without_message(
    settings, session_stub, client_stub
) -> None:
    await dispatch_update(
        {"update_id": 3, "channel_post": {}},
        settings=settings,
        client=client_stub,
        session=session_stub,
    )
    client_stub.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_catches_handler_exception_and_replies(
    settings, session_stub, client_stub, monkeypatch
) -> None:
    """A buggy command handler must not bubble up — the user gets a soft message."""
    from app.bot import handlers as handlers_module

    async def boom(ctx):  # type: ignore[no-untyped-def]
        raise RuntimeError("kaboom")

    monkeypatch.setitem(handlers_module.COMMAND_HANDLERS, "start", boom)

    update = {
        "update_id": 4,
        "message": {
            "chat": {"id": 11},
            "from": {"id": 7},
            "text": "/start",
        },
    }
    await dispatch_update(
        update,
        settings=settings,
        client=client_stub,
        session=session_stub,
    )
    args, _ = client_stub.send_message.await_args
    assert args[0] == 11
    assert "wrong" in args[1].lower() or "try again" in args[1].lower()


@pytest.mark.asyncio
async def test_dispatch_callback_query_acks_and_dispatches(
    settings, session_stub, client_stub, monkeypatch
) -> None:
    from app.bot import handlers as handlers_module

    called: list[Any] = []

    async def fake_balance(ctx):  # type: ignore[no-untyped-def]
        called.append(ctx.chat_id)

    monkeypatch.setitem(
        handlers_module._CALLBACK_TO_COMMAND, "menu:balance", fake_balance
    )

    update = {
        "update_id": 5,
        "callback_query": {
            "id": "cb1",
            "from": {"id": 7, "first_name": "Bob"},
            "message": {"chat": {"id": 42}, "message_id": 9},
            "data": "menu:balance",
        },
    }
    await dispatch_update(
        update,
        settings=settings,
        client=client_stub,
        session=session_stub,
    )
    client_stub.answer_callback_query.assert_awaited_once_with("cb1")
    assert called == [42]
