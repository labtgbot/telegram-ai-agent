"""Tests for the admin refresh-session cleanup worker."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest


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


class _Settings:
    admin_refresh_token_ttl = 600


def _install_session(monkeypatch) -> _FakeSession:
    from app.workers import admin_refresh_sessions as worker_module

    session = _FakeSession()

    def fake_factory():
        return lambda: session

    monkeypatch.setattr(worker_module, "get_session_factory", fake_factory)
    monkeypatch.setattr(worker_module, "get_settings", lambda: _Settings())
    return session


@pytest.mark.asyncio
async def test_run_admin_refresh_session_cleanup_commits_and_passes_retention(
    monkeypatch,
) -> None:
    from app.workers import admin_refresh_sessions as worker_module

    session = _install_session(monkeypatch)
    reference = datetime(2026, 6, 15, 12, tzinfo=UTC)
    captured: dict[str, object] = {}

    async def fake_cleanup(passed_session, *, now, revoked_retention_seconds):
        captured["session"] = passed_session
        captured["now"] = now
        captured["revoked_retention_seconds"] = revoked_retention_seconds
        return 4

    monkeypatch.setattr(worker_module, "cleanup_refresh_sessions", fake_cleanup)

    deleted = await worker_module.run_admin_refresh_session_cleanup(now=reference)

    assert deleted == 4
    assert captured["session"] is session
    assert captured["now"] == reference
    assert captured["revoked_retention_seconds"] == 600
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


@pytest.mark.asyncio
async def test_run_admin_refresh_session_cleanup_rolls_back_on_failure(monkeypatch) -> None:
    from app.workers import admin_refresh_sessions as worker_module

    session = _install_session(monkeypatch)

    async def fake_cleanup(*_args, **_kwargs):
        raise RuntimeError("simulated cleanup failure")

    monkeypatch.setattr(worker_module, "cleanup_refresh_sessions", fake_cleanup)

    with pytest.raises(RuntimeError, match="simulated cleanup failure"):
        await worker_module.run_admin_refresh_session_cleanup()

    assert session.committed is False
    assert session.rolled_back is True


def test_main_returns_zero_on_success(monkeypatch, capsys) -> None:
    from app.workers import admin_refresh_sessions as worker_module

    async def fake_run():
        return 3

    monkeypatch.setattr(worker_module, "run_admin_refresh_session_cleanup", fake_run)

    assert worker_module.main() == 0
    assert "deleted=3" in capsys.readouterr().out


def test_main_returns_one_on_failure(monkeypatch) -> None:
    from app.workers import admin_refresh_sessions as worker_module

    async def fake_run():
        raise RuntimeError("nope")

    monkeypatch.setattr(worker_module, "run_admin_refresh_session_cleanup", fake_run)

    assert worker_module.main() == 1
