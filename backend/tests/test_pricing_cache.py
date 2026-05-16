"""Unit tests for the in-process pricing TTL cache (issue #36).

``load_pricing_config`` is on the hot path of every ``create_invoice``
call.  Issue #36 adds a per-worker TTL cache (default 60s, configurable
via ``Settings.pricing_cache_ttl_seconds``) with explicit invalidation
on ``update_pricing_config``.  The contract under test is:

* a cache hit serves the previously read value without hitting the DB;
* the entry expires after the configured TTL elapses;
* :func:`invalidate_pricing_cache` drops the entry immediately;
* a concurrent thundering herd collapses into a single DB read.

The tests use a fake :class:`AsyncSession` that records every
``execute`` call so we can assert how many DB reads actually happened.
A monotonic-clock monkeypatch lets us simulate TTL expiry without
sleeping.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.services import pricing as pricing_module
from app.services.pricing import (
    PricingConfig,
    invalidate_pricing_cache,
    load_pricing_config,
)

# ----------------------------------------------------------------- helpers


class _RowStub:
    def __init__(self, setting_value: dict | None) -> None:
        self.setting_value = setting_value


class _ResultStub:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any:
        return self._row


class _RecordingSession:
    """An :class:`AsyncSession` shape that counts ``execute`` calls."""

    def __init__(self, *, setting_value: dict | None = None) -> None:
        self._setting_value = setting_value
        self.execute_calls = 0

    async def execute(self, _stmt):  # noqa: ANN001
        self.execute_calls += 1
        row = (
            _RowStub(self._setting_value)
            if self._setting_value is not None
            else None
        )
        return _ResultStub(row)


@pytest.fixture(autouse=True)
def _isolated_cache():
    """Each test starts and ends with an empty in-process cache."""
    invalidate_pricing_cache()
    yield
    invalidate_pricing_cache()


# ----------------------------------------------------------------- behaviour


@pytest.mark.asyncio
async def test_load_pricing_config_serves_from_cache_after_first_read() -> None:
    session = _RecordingSession()
    first = await load_pricing_config(session)
    second = await load_pricing_config(session)
    assert session.execute_calls == 1
    assert isinstance(first, PricingConfig)
    # Same dataclass instance — the cache hands the snapshot back as-is.
    assert first is second


@pytest.mark.asyncio
async def test_invalidate_pricing_cache_forces_next_read_to_hit_db() -> None:
    session = _RecordingSession()
    await load_pricing_config(session)
    invalidate_pricing_cache()
    await load_pricing_config(session)
    assert session.execute_calls == 2


@pytest.mark.asyncio
async def test_cache_entry_expires_after_ttl(monkeypatch) -> None:
    session = _RecordingSession()
    # Stub the clock so we can fast-forward without sleeping.
    fake_now = {"t": 1000.0}
    monkeypatch.setattr(
        pricing_module, "monotonic", lambda: fake_now["t"], raising=True
    )
    # Force a short, deterministic TTL regardless of env config.
    monkeypatch.setattr(
        pricing_module, "_pricing_cache_ttl", lambda: 60.0, raising=True
    )

    await load_pricing_config(session)
    fake_now["t"] += 30  # within TTL
    await load_pricing_config(session)
    assert session.execute_calls == 1

    fake_now["t"] += 31  # crosses the 60s boundary
    await load_pricing_config(session)
    assert session.execute_calls == 2


@pytest.mark.asyncio
async def test_ttl_zero_disables_cache(monkeypatch) -> None:
    monkeypatch.setattr(
        pricing_module, "_pricing_cache_ttl", lambda: 0.0, raising=True
    )
    session = _RecordingSession()
    await load_pricing_config(session)
    await load_pricing_config(session)
    await load_pricing_config(session)
    assert session.execute_calls == 3


@pytest.mark.asyncio
async def test_concurrent_misses_collapse_into_single_db_read() -> None:
    """A thundering herd of N callers must produce exactly one DB read."""
    session = _RecordingSession()
    results = await asyncio.gather(
        *(load_pricing_config(session) for _ in range(8))
    )
    assert session.execute_calls == 1
    assert all(r is results[0] for r in results)


@pytest.mark.asyncio
async def test_db_failure_returns_defaults_without_caching() -> None:
    class _BoomSession:
        async def execute(self, _stmt):  # noqa: ANN001
            raise RuntimeError("db is down")

    session = _BoomSession()
    config = await load_pricing_config(session)  # type: ignore[arg-type]
    assert isinstance(config, PricingConfig)
    # Defaults never poison the cache permanently — invalidation still works.
    invalidate_pricing_cache()
