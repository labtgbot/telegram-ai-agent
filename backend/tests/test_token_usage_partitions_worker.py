"""Tests for the token usage partition maintenance worker."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.services.token_usage_partitions import TokenUsagePartitionMaintenanceResult


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
    from app.workers import token_usage_partitions as worker_module

    session = _FakeSession()

    def fake_factory():
        return lambda: session

    monkeypatch.setattr(worker_module, "get_session_factory", fake_factory)
    return session


@pytest.mark.asyncio
async def test_run_partition_maintenance_commits_and_passes_options(monkeypatch) -> None:
    from app.workers import token_usage_partitions as worker_module

    session = _install_session(monkeypatch)
    reference = datetime(2026, 6, 15, tzinfo=UTC)
    captured: dict[str, object] = {}

    async def fake_ensure(passed_session, *, reference_date, months_ahead):
        captured["session"] = passed_session
        captured["reference_date"] = reference_date
        captured["months_ahead"] = months_ahead
        return TokenUsagePartitionMaintenanceResult(
            default_created=True,
            partitions_created=("token_usage_logs_2026_06",),
            rows_moved=0,
        )

    monkeypatch.setattr(worker_module, "ensure_token_usage_partitions", fake_ensure)

    result = await worker_module.run_token_usage_partition_maintenance(
        reference_date=reference,
        months_ahead=3,
    )

    assert result.default_created is True
    assert result.partitions_created == ("token_usage_logs_2026_06",)
    assert captured["session"] is session
    assert captured["reference_date"] == reference
    assert captured["months_ahead"] == 3
    assert session.committed is True
    assert session.rolled_back is False
    assert session.closed is True


@pytest.mark.asyncio
async def test_run_partition_maintenance_rolls_back_on_failure(monkeypatch) -> None:
    from app.workers import token_usage_partitions as worker_module

    session = _install_session(monkeypatch)

    async def fake_ensure(*_args, **_kwargs):
        raise RuntimeError("simulated DDL failure")

    monkeypatch.setattr(worker_module, "ensure_token_usage_partitions", fake_ensure)

    with pytest.raises(RuntimeError, match="simulated DDL failure"):
        await worker_module.run_token_usage_partition_maintenance()

    assert session.committed is False
    assert session.rolled_back is True


def test_parse_args_accepts_reference_date_and_months_ahead() -> None:
    from app.workers.token_usage_partitions import _parse_args

    args = _parse_args(["--reference-date", "2026-06-15T12:00:00+00:00", "--months-ahead", "4"])

    assert args.reference_date == datetime(2026, 6, 15, 12, tzinfo=UTC)
    assert args.months_ahead == 4


def test_main_returns_zero_on_success(monkeypatch, capsys) -> None:
    from app.workers import token_usage_partitions as worker_module

    async def fake_run(*, reference_date, months_ahead):  # noqa: ANN001
        return TokenUsagePartitionMaintenanceResult(
            default_created=False,
            partitions_created=("token_usage_logs_2026_07", "token_usage_logs_2026_08"),
            rows_moved=3,
        )

    monkeypatch.setattr(worker_module, "run_token_usage_partition_maintenance", fake_run)

    code = worker_module.main(["--months-ahead", "2"])

    assert code == 0
    out = capsys.readouterr().out
    assert "default_created=0" in out
    assert "partitions_created=2" in out
    assert "rows_moved=3" in out


def test_main_returns_one_on_failure(monkeypatch) -> None:
    from app.workers import token_usage_partitions as worker_module

    async def fake_run(*, reference_date, months_ahead):  # noqa: ANN001
        raise RuntimeError("nope")

    monkeypatch.setattr(worker_module, "run_token_usage_partition_maintenance", fake_run)

    assert worker_module.main([]) == 1
