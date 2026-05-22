"""Tests for the ``run_broadcast_pass`` worker (issue #28).

The drain loop and audience SQL are covered by
``test_broadcast_service.py``.  Here we verify the worker's outer
contract: it owns/closes its own Telegram client when none is supplied,
skips politely when ``telegram_bot_token`` is unset, fans out across
every due broadcast, and rolls back + continues when ``drain_broadcast``
raises for one of them.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

# Break the ``app.services.payments`` ↔ ``app.bot.handlers`` import cycle
# before importing the worker (same pattern as the other admin tests).
from app.bot.client import TelegramApiError  # noqa: F401


class _FakeSession:
    def __init__(self) -> None:
        self.committed = False
        self.rolled_back = False
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.closed = True
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def _install_session(monkeypatch) -> _FakeSession:
    """Override ``get_session_factory`` to return our fake session."""
    from app.workers import broadcast as worker_module

    session = _FakeSession()

    def fake_factory():
        return lambda: session  # session itself is the async context manager

    monkeypatch.setattr(worker_module, "get_session_factory", fake_factory)
    return session


class _FakeTelegramClient:
    """Minimal ``TelegramClient`` stand-in that records close()."""

    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _broadcast(id_: int) -> SimpleNamespace:
    return SimpleNamespace(id=id_)


# ------------------------------------------------------------- happy path


@pytest.mark.asyncio
async def test_pass_uses_supplied_client_and_does_not_close_it(monkeypatch) -> None:
    from app.workers import broadcast as worker_module

    session = _install_session(monkeypatch)
    captured: dict[str, Any] = {"drained": []}

    async def fake_list_due(passed_session, *, now, limit):
        captured["session"] = passed_session
        captured["now"] = now
        captured["limit"] = limit
        return [_broadcast(11), _broadcast(22)]

    async def fake_drain(passed_session, client, *, broadcast, rate_limit):
        captured["drained"].append(broadcast.id)
        captured["drain_session"] = passed_session
        captured["drain_client"] = client
        captured["rate_limit"] = rate_limit

    monkeypatch.setattr(worker_module, "list_due_broadcasts", fake_list_due)
    monkeypatch.setattr(worker_module, "drain_broadcast", fake_drain)

    client = _FakeTelegramClient()
    now = datetime(2026, 5, 16, 12, 0, tzinfo=UTC)
    touched = await worker_module.run_broadcast_pass(
        client=client,
        rate_limit=12,
        max_broadcasts=7,
        now=now,
    )

    assert touched == 2
    assert captured["drained"] == [11, 22]
    assert captured["session"] is session
    assert captured["drain_session"] is session
    assert captured["drain_client"] is client
    assert captured["now"] == now
    assert captured["limit"] == 7
    assert captured["rate_limit"] == 12
    # Caller supplied the client → worker must NOT close it.
    assert client.closed is False
    assert session.closed is True


@pytest.mark.asyncio
async def test_pass_returns_zero_when_no_due_broadcasts(monkeypatch) -> None:
    from app.workers import broadcast as worker_module

    _install_session(monkeypatch)

    async def fake_list_due(_session, *, now, limit):  # noqa: ARG001
        return []

    async def fake_drain(*_args, **_kwargs):  # pragma: no cover — never called
        raise AssertionError("drain should not run when no due broadcasts")

    monkeypatch.setattr(worker_module, "list_due_broadcasts", fake_list_due)
    monkeypatch.setattr(worker_module, "drain_broadcast", fake_drain)

    touched = await worker_module.run_broadcast_pass(
        client=_FakeTelegramClient(),
    )

    assert touched == 0


# -------------------------------------------------------- token handling


@pytest.mark.asyncio
async def test_pass_skips_when_no_bot_token(monkeypatch) -> None:
    from app.workers import broadcast as worker_module

    _install_session(monkeypatch)

    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="",
            telegram_api_base_url="https://api.telegram.org",
        ),
    )

    async def fake_list_due(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("list_due should not run when no token")

    monkeypatch.setattr(worker_module, "list_due_broadcasts", fake_list_due)

    touched = await worker_module.run_broadcast_pass()
    assert touched == 0


@pytest.mark.asyncio
async def test_pass_creates_and_closes_own_client_when_none_supplied(
    monkeypatch,
) -> None:
    from app.workers import broadcast as worker_module

    session = _install_session(monkeypatch)
    constructed: list[_FakeTelegramClient] = []

    def fake_client_ctor(token, *, base_url):
        client = _FakeTelegramClient()
        client.token = token  # type: ignore[attr-defined]
        client.base_url = base_url  # type: ignore[attr-defined]
        constructed.append(client)
        return client

    monkeypatch.setattr(worker_module, "TelegramClient", fake_client_ctor)
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="bot:TEST",
            telegram_api_base_url="https://api.telegram.org",
        ),
    )

    async def fake_list_due(_session, *, now, limit):  # noqa: ARG001
        return [_broadcast(99)]

    drained: list[int] = []

    async def fake_drain(_session, client, *, broadcast, rate_limit):  # noqa: ARG001
        drained.append(broadcast.id)
        # The client the drain receives should be the one the worker built.
        assert client is constructed[0]

    monkeypatch.setattr(worker_module, "list_due_broadcasts", fake_list_due)
    monkeypatch.setattr(worker_module, "drain_broadcast", fake_drain)

    touched = await worker_module.run_broadcast_pass()

    assert touched == 1
    assert drained == [99]
    assert len(constructed) == 1
    assert constructed[0].token == "bot:TEST"
    assert constructed[0].base_url == "https://api.telegram.org"
    # Worker owns the client → must close it before returning.
    assert constructed[0].closed is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_pass_closes_own_client_even_when_list_due_raises(
    monkeypatch,
) -> None:
    from app.workers import broadcast as worker_module

    _install_session(monkeypatch)
    constructed: list[_FakeTelegramClient] = []

    def fake_client_ctor(*_args, **_kwargs):
        client = _FakeTelegramClient()
        constructed.append(client)
        return client

    monkeypatch.setattr(worker_module, "TelegramClient", fake_client_ctor)
    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="bot:TEST",
            telegram_api_base_url="https://api.telegram.org",
        ),
    )

    async def boom(*_args, **_kwargs):
        raise RuntimeError("db went away")

    monkeypatch.setattr(worker_module, "list_due_broadcasts", boom)

    with pytest.raises(RuntimeError, match="db went away"):
        await worker_module.run_broadcast_pass()

    # Even on failure, the owned client must be closed.
    assert constructed[0].closed is True


# ----------------------------------------------------- partial failure


@pytest.mark.asyncio
async def test_pass_rolls_back_and_continues_when_one_broadcast_fails(
    monkeypatch,
) -> None:
    from app.workers import broadcast as worker_module

    session = _install_session(monkeypatch)

    async def fake_list_due(_session, *, now, limit):  # noqa: ARG001
        return [_broadcast(1), _broadcast(2), _broadcast(3)]

    drained: list[int] = []

    async def fake_drain(_session, _client, *, broadcast, rate_limit):  # noqa: ARG001
        if broadcast.id == 2:
            raise RuntimeError("kaboom")
        drained.append(broadcast.id)

    monkeypatch.setattr(worker_module, "list_due_broadcasts", fake_list_due)
    monkeypatch.setattr(worker_module, "drain_broadcast", fake_drain)

    touched = await worker_module.run_broadcast_pass(
        client=_FakeTelegramClient(),
    )

    # Two succeeded, one failed → touched counts only successes.
    assert touched == 2
    assert drained == [1, 3]
    # Session rollback was called for the failing broadcast.
    assert session.rolled_back is True


# ---------------------------------------------------------- CLI / main


def test_main_runs_single_pass_and_returns_zero(monkeypatch, capsys) -> None:
    from app.workers import broadcast as worker_module

    captured: dict[str, Any] = {}

    async def fake_pass(*, rate_limit, **_kwargs):
        captured["rate_limit"] = rate_limit
        return 3

    monkeypatch.setattr(worker_module, "run_broadcast_pass", fake_pass)
    monkeypatch.setattr("sys.argv", ["app.workers.broadcast", "--rate-limit", "10"])

    code = worker_module.main()

    assert code == 0
    assert captured["rate_limit"] == 10
    assert "broadcasts_processed=3" in capsys.readouterr().out


def test_main_returns_one_when_pass_raises(monkeypatch) -> None:
    from app.workers import broadcast as worker_module

    async def fake_pass(**_kwargs):
        raise RuntimeError("worker boom")

    monkeypatch.setattr(worker_module, "run_broadcast_pass", fake_pass)
    monkeypatch.setattr("sys.argv", ["app.workers.broadcast"])

    code = worker_module.main()
    assert code == 1


def test_main_returns_zero_on_keyboard_interrupt(monkeypatch) -> None:
    from app.workers import broadcast as worker_module

    async def fake_pass(**_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker_module, "run_broadcast_pass", fake_pass)
    monkeypatch.setattr("sys.argv", ["app.workers.broadcast"])

    code = worker_module.main()
    assert code == 0


def test_main_invokes_loop_when_flag_set(monkeypatch) -> None:
    from app.workers import broadcast as worker_module

    captured: dict[str, Any] = {}

    async def fake_loop(*, rate_limit):
        captured["rate_limit"] = rate_limit

    async def fake_pass(**_kwargs):  # pragma: no cover — not called in --loop
        raise AssertionError("pass should not run when --loop is set")

    monkeypatch.setattr(worker_module, "run_broadcast_loop", fake_loop)
    monkeypatch.setattr(worker_module, "run_broadcast_pass", fake_pass)
    monkeypatch.setattr(
        "sys.argv",
        ["app.workers.broadcast", "--loop", "--rate-limit", "20"],
    )

    code = worker_module.main()
    assert code == 0
    assert captured["rate_limit"] == 20


# -------------------------------------------------------------- loop mode


@pytest.mark.asyncio
async def test_loop_skips_when_no_bot_token(monkeypatch) -> None:
    from app.workers import broadcast as worker_module

    monkeypatch.setattr(
        worker_module,
        "get_settings",
        lambda: SimpleNamespace(
            telegram_bot_token="",
            telegram_api_base_url="https://api.telegram.org",
        ),
    )

    # If the loop somehow tried to build a client we'd see this fail.
    def boom_ctor(*_args, **_kwargs):  # pragma: no cover
        raise AssertionError("TelegramClient must not be constructed without a token")

    monkeypatch.setattr(worker_module, "TelegramClient", boom_ctor)

    # Returns immediately — no iteration, no client construction.
    await worker_module.run_broadcast_loop()
