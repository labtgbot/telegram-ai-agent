"""Tests for the ``process_due_deletions`` worker.

Service-level logic (``anonymise_user`` / ``list_due_deletions``) is
covered by ``test_account_deletion_service.py``; here we verify the
worker glue: it commits on success, rolls back and re-raises on a fatal
failure, and counts per-row failures without aborting the run.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest


class _FakeRequest:
    def __init__(self, *, request_id: int, user_id: int) -> None:
        self.id = request_id
        self.user_id = user_id
        self.status = "pending"
        self.failed_at = None
        self.failure_reason = None
        self.scheduled_for = datetime(2026, 5, 1, tzinfo=UTC)


class _FakeSession:
    def __init__(self) -> None:
        self.commit_count = 0
        self.rollback_count = 0
        self.needs_rollback = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self) -> None:
        if self.needs_rollback:
            raise RuntimeError("transaction requires rollback")
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1
        self.needs_rollback = False

    @property
    def committed(self) -> bool:
        return self.commit_count > 0

    @property
    def rolled_back(self) -> bool:
        return self.rollback_count > 0


def _install_session(monkeypatch) -> _FakeSession:
    from app.workers import account_deletion as worker_module

    session = _FakeSession()

    def fake_factory():
        return lambda: session

    monkeypatch.setattr(worker_module, "get_session_factory", fake_factory)
    return session


@pytest.mark.asyncio
async def test_processes_due_requests_and_commits(monkeypatch) -> None:
    from app.workers import account_deletion as worker_module

    session = _install_session(monkeypatch)
    due = [
        _FakeRequest(request_id=1, user_id=10),
        _FakeRequest(request_id=2, user_id=11),
    ]

    async def fake_list(session_arg, *, now=None, limit=100):
        return list(due)

    async def fake_anonymise(session_arg, *, user_id, now=None):
        return True

    async def fake_mark(session_arg, *, request, now=None):
        request.status = "completed"

    monkeypatch.setattr(worker_module, "list_due_deletions", fake_list)
    monkeypatch.setattr(worker_module, "anonymise_user", fake_anonymise)
    monkeypatch.setattr(worker_module, "mark_deletion_completed", fake_mark)

    result = await worker_module.process_due_deletions()

    assert result.processed == 2
    assert result.anonymised == 2
    assert result.failed == 0
    assert session.committed is True
    assert session.rolled_back is False


@pytest.mark.asyncio
async def test_records_per_row_failures_without_aborting(monkeypatch) -> None:
    from app.workers import account_deletion as worker_module

    session = _install_session(monkeypatch)
    due = [
        _FakeRequest(request_id=1, user_id=10),
        _FakeRequest(request_id=2, user_id=11),
    ]

    async def fake_list(session_arg, *, now=None, limit=100):
        return list(due)

    async def fake_anonymise(session_arg, *, user_id, now=None):
        if user_id == 11:
            session_arg.needs_rollback = True
            raise RuntimeError("simulated db error")
        return True

    async def fake_mark(session_arg, *, request, now=None):
        request.status = "completed"

    async def fake_mark_failed(session_arg, *, request_id, failure_reason, now=None):
        failed_request = next(request for request in due if request.id == request_id)
        failed_request.status = "failed"
        failed_request.failed_at = now
        failed_request.failure_reason = failure_reason

    monkeypatch.setattr(worker_module, "list_due_deletions", fake_list)
    monkeypatch.setattr(worker_module, "anonymise_user", fake_anonymise)
    monkeypatch.setattr(worker_module, "mark_deletion_completed", fake_mark)
    monkeypatch.setattr(worker_module, "mark_deletion_failed", fake_mark_failed)

    result = await worker_module.process_due_deletions()

    assert result.processed == 2
    assert result.anonymised == 1
    assert result.failed == 1
    # Per-row failures must mark the row as failed but still commit so
    # successful rows are not lost.
    assert due[1].status == "failed"
    assert due[1].failure_reason == "RuntimeError: simulated db error"
    assert session.committed is True
    assert session.commit_count == 2
    assert session.rollback_count == 1


@pytest.mark.asyncio
async def test_failed_requests_do_not_block_later_runs(monkeypatch) -> None:
    from app.workers import account_deletion as worker_module

    _install_session(monkeypatch)
    due = [
        _FakeRequest(request_id=1, user_id=10),
        _FakeRequest(request_id=2, user_id=11),
    ]
    processed_users: list[int] = []

    async def fake_list(session_arg, *, now=None, limit=100):
        return [request for request in due if request.status == "pending"]

    async def fake_anonymise(session_arg, *, user_id, now=None):
        processed_users.append(user_id)
        if user_id == 11:
            session_arg.needs_rollback = True
            raise RuntimeError("simulated db error")
        return True

    async def fake_mark(session_arg, *, request, now=None):
        request.status = "completed"

    async def fake_mark_failed(session_arg, *, request_id, failure_reason, now=None):
        failed_request = next(request for request in due if request.id == request_id)
        failed_request.status = "failed"
        failed_request.failed_at = now
        failed_request.failure_reason = failure_reason

    monkeypatch.setattr(worker_module, "list_due_deletions", fake_list)
    monkeypatch.setattr(worker_module, "anonymise_user", fake_anonymise)
    monkeypatch.setattr(worker_module, "mark_deletion_completed", fake_mark)
    monkeypatch.setattr(worker_module, "mark_deletion_failed", fake_mark_failed)

    first = await worker_module.process_due_deletions()
    due.append(_FakeRequest(request_id=3, user_id=12))
    second = await worker_module.process_due_deletions()

    assert first.processed == 2
    assert first.failed == 1
    assert due[1].status == "failed"
    assert second.processed == 1
    assert second.failed == 0
    assert processed_users == [10, 11, 12]


@pytest.mark.asyncio
async def test_idempotent_anonymise_does_not_count_as_anonymised(monkeypatch) -> None:
    from app.workers import account_deletion as worker_module

    _install_session(monkeypatch)
    due = [_FakeRequest(request_id=1, user_id=10)]

    async def fake_list(session_arg, *, now=None, limit=100):
        return list(due)

    async def fake_anonymise(session_arg, *, user_id, now=None):
        return False  # idempotent — user was already anonymised

    async def fake_mark(session_arg, *, request, now=None):
        request.status = "completed"

    monkeypatch.setattr(worker_module, "list_due_deletions", fake_list)
    monkeypatch.setattr(worker_module, "anonymise_user", fake_anonymise)
    monkeypatch.setattr(worker_module, "mark_deletion_completed", fake_mark)

    result = await worker_module.process_due_deletions()
    assert result.processed == 1
    assert result.anonymised == 0
    assert result.failed == 0


@pytest.mark.asyncio
async def test_rolls_back_and_raises_on_fatal_failure(monkeypatch) -> None:
    from app.workers import account_deletion as worker_module

    session = _install_session(monkeypatch)

    async def fake_list(session_arg, *, now=None, limit=100):
        raise RuntimeError("simulated infra failure")

    monkeypatch.setattr(worker_module, "list_due_deletions", fake_list)

    with pytest.raises(RuntimeError):
        await worker_module.process_due_deletions()

    assert session.committed is False
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_passes_now_through_to_listing(monkeypatch) -> None:
    from app.workers import account_deletion as worker_module

    _install_session(monkeypatch)
    captured: dict[str, datetime | None] = {"now": None}

    async def fake_list(session_arg, *, now=None, limit=100):
        captured["now"] = now
        return []

    monkeypatch.setattr(worker_module, "list_due_deletions", fake_list)

    fixed = datetime(2026, 5, 16, 12, tzinfo=UTC)
    result = await worker_module.process_due_deletions(now=fixed)
    assert result.processed == 0
    assert captured["now"] == fixed
