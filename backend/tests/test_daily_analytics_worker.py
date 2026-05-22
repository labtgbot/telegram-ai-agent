"""Tests for the ``run_daily_analytics`` worker (issue #27).

The aggregation logic itself is covered by
``test_admin_analytics_service.py``.  Here we verify the worker's
contract: it commits on success, rolls back and re-raises on failure,
and resolves the default ``snapshot_date`` to yesterday in UTC.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

# Break the ``app.services.payments`` ↔ ``app.bot.handlers`` import cycle
# before importing the worker (same pattern as the other admin tests).
from app.bot.client import TelegramApiError  # noqa: F401


class _FakeSnapshot:
    def __init__(self, target: date) -> None:
        self.new_users = 1
        self.active_users = 2
        self.total_stars_revenue = 100
        self.date = target


class _FakeResult:
    def __init__(self, target: date, *, created: bool = True) -> None:
        self.snapshot_date = target
        self.created = created
        self.snapshot = _FakeSnapshot(target)


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
    from app.workers import daily_analytics as worker_module

    session = _FakeSession()

    def fake_factory():
        return lambda: session  # session itself is the async context manager

    monkeypatch.setattr(worker_module, "get_session_factory", fake_factory)
    return session


@pytest.mark.asyncio
async def test_run_daily_analytics_commits_on_success(monkeypatch) -> None:
    from app.workers import daily_analytics as worker_module

    session = _install_session(monkeypatch)
    target = date(2026, 5, 10)
    seen: dict[str, object] = {}

    async def fake_aggregate(passed_session, *, snapshot_date):
        seen["session"] = passed_session
        seen["snapshot_date"] = snapshot_date
        return _FakeResult(snapshot_date, created=True)

    monkeypatch.setattr(
        worker_module, "aggregate_daily_snapshot", fake_aggregate
    )

    result = await worker_module.run_daily_analytics(snapshot_date=target)

    assert result.snapshot_date == target
    assert result.created is True
    assert seen["session"] is session
    assert seen["snapshot_date"] == target
    assert session.committed is True
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_run_daily_analytics_defaults_to_yesterday_utc(monkeypatch) -> None:
    from app.workers import daily_analytics as worker_module

    _install_session(monkeypatch)
    captured: dict[str, date] = {}

    async def fake_aggregate(_session, *, snapshot_date):
        captured["target"] = snapshot_date
        return _FakeResult(snapshot_date, created=True)

    monkeypatch.setattr(
        worker_module, "aggregate_daily_snapshot", fake_aggregate
    )

    expected = datetime.now(UTC).date() - timedelta(days=1)
    await worker_module.run_daily_analytics()

    assert captured["target"] == expected


@pytest.mark.asyncio
async def test_run_daily_analytics_rolls_back_on_failure(monkeypatch) -> None:
    from app.workers import daily_analytics as worker_module

    session = _install_session(monkeypatch)

    async def boom(_session, *, snapshot_date):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(worker_module, "aggregate_daily_snapshot", boom)

    with pytest.raises(RuntimeError, match="simulated DB failure"):
        await worker_module.run_daily_analytics(snapshot_date=date(2026, 5, 1))

    assert session.rolled_back is True
    assert session.committed is False


def test_parse_args_accepts_date_flag() -> None:
    from app.workers.daily_analytics import _parse_args

    ns = _parse_args(["--date", "2026-04-15"])
    assert ns.date == date(2026, 4, 15)


def test_parse_args_defaults_date_to_none() -> None:
    from app.workers.daily_analytics import _parse_args

    ns = _parse_args([])
    assert ns.date is None


def test_main_returns_zero_on_success(monkeypatch, capsys) -> None:
    from app.workers import daily_analytics as worker_module

    async def fake_run(*, snapshot_date):  # noqa: ANN001
        return _FakeResult(snapshot_date or date(2026, 5, 1), created=True)

    monkeypatch.setattr(worker_module, "run_daily_analytics", fake_run)
    code = worker_module.main(["--date", "2026-05-01"])
    assert code == 0
    out = capsys.readouterr().out
    assert "snapshot_date=2026-05-01" in out
    assert "created=1" in out
    assert "new_users=1" in out


def test_main_returns_one_on_failure(monkeypatch) -> None:
    from app.workers import daily_analytics as worker_module

    async def fake_run(*, snapshot_date):  # noqa: ANN001
        raise RuntimeError("nope")

    monkeypatch.setattr(worker_module, "run_daily_analytics", fake_run)
    code = worker_module.main([])
    assert code == 1
