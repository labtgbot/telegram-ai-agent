"""Unit tests for :mod:`app.services.balance_cache`.

The :class:`BalanceCache` is a thin wrapper over Redis — the contract we
care about is:

* miss → ``None``; hit → integer;
* corrupted values are dropped and treated as a miss;
* ``set`` writes the configured TTL;
* ``invalidate`` / ``invalidate_many`` issue exactly one ``DELETE``;
* the singleton helper returns the same instance until explicitly reset.

No real Redis required; a small in-memory fake exposes the
``get`` / ``set`` / ``delete`` async surface we actually use.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.services.balance_cache import (
    KEY_PREFIX,
    BalanceCache,
    cache_key,
    get_default_balance_cache,
    reset_default_balance_cache,
)


class FakeRedis:
    """Minimal async ``redis.asyncio.Redis`` stand-in for unit tests."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.last_ttl: int | None = None
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, str, int | None]] = []
        self.delete_calls: list[tuple[str, ...]] = []

    async def get(self, name: str) -> str | None:
        self.get_calls.append(name)
        return self.store.get(name)

    async def set(self, name: str, value: Any, ex: int | None = None) -> bool:
        self.set_calls.append((name, str(value), ex))
        self.last_ttl = ex
        self.store[name] = str(value)
        return True

    async def delete(self, *names: str) -> int:
        self.delete_calls.append(names)
        removed = 0
        for n in names:
            if n in self.store:
                del self.store[n]
                removed += 1
        return removed


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def cache(fake_redis: FakeRedis) -> BalanceCache:
    # An explicit TTL avoids depending on app settings inside unit tests.
    return BalanceCache(fake_redis, ttl_seconds=300)


# ----------------------------------------------------------------- cache_key


def test_cache_key_format() -> None:
    assert cache_key(42) == f"{KEY_PREFIX}42"
    assert cache_key("99") == f"{KEY_PREFIX}99"  # type: ignore[arg-type]


# ---------------------------------------------------------- read / write paths


@pytest.mark.asyncio
async def test_get_returns_none_on_miss(cache: BalanceCache) -> None:
    assert await cache.get(1) is None


@pytest.mark.asyncio
async def test_set_then_get_round_trip(
    cache: BalanceCache, fake_redis: FakeRedis
) -> None:
    await cache.set(7, 250)
    assert fake_redis.last_ttl == cache.ttl_seconds
    assert await cache.get(7) == 250


@pytest.mark.asyncio
async def test_get_drops_corrupted_value(
    cache: BalanceCache, fake_redis: FakeRedis
) -> None:
    fake_redis.store[cache_key(42)] = "not-a-number"
    assert await cache.get(42) is None
    # The bad value must be deleted so the next read forces a refresh.
    assert cache_key(42) not in fake_redis.store
    assert fake_redis.delete_calls, "corrupted value must trigger DELETE"


@pytest.mark.asyncio
async def test_set_coerces_balance_to_int(
    cache: BalanceCache, fake_redis: FakeRedis
) -> None:
    await cache.set(3, 100.0)  # type: ignore[arg-type]
    assert fake_redis.store[cache_key(3)] == "100"


# ------------------------------------------------------------- invalidation


@pytest.mark.asyncio
async def test_invalidate_removes_key(
    cache: BalanceCache, fake_redis: FakeRedis
) -> None:
    await cache.set(11, 500)
    await cache.invalidate(11)
    assert cache_key(11) not in fake_redis.store
    assert await cache.get(11) is None


@pytest.mark.asyncio
async def test_invalidate_many_skips_empty_input(
    cache: BalanceCache, fake_redis: FakeRedis
) -> None:
    await cache.invalidate_many([])
    assert fake_redis.delete_calls == []


@pytest.mark.asyncio
async def test_invalidate_many_issues_single_delete(
    cache: BalanceCache, fake_redis: FakeRedis
) -> None:
    await cache.set(1, 10)
    await cache.set(2, 20)
    await cache.set(3, 30)
    await cache.invalidate_many([1, 2, 3])
    assert len(fake_redis.delete_calls) == 1
    assert set(fake_redis.delete_calls[0]) == {
        cache_key(1),
        cache_key(2),
        cache_key(3),
    }
    assert fake_redis.store == {}


# -------------------------------------------------------------- TTL clamping


def test_ttl_floor_is_one_second(fake_redis: FakeRedis) -> None:
    # ``ex=0`` collapses to a delete in real Redis; the cache must clamp it
    # so set() always stores a value.
    cache = BalanceCache(fake_redis, ttl_seconds=0)
    assert cache.ttl_seconds == 1
    cache_neg = BalanceCache(fake_redis, ttl_seconds=-99)
    assert cache_neg.ttl_seconds == 1


# ------------------------------------------------------- default-cache helper


def test_get_default_balance_cache_returns_singleton(monkeypatch) -> None:
    reset_default_balance_cache()
    fake = FakeRedis()
    monkeypatch.setattr(
        "app.core.redis.get_redis", lambda: fake, raising=True
    )
    first = get_default_balance_cache()
    second = get_default_balance_cache()
    try:
        assert first is second
        assert isinstance(first, BalanceCache)
    finally:
        reset_default_balance_cache()


def test_reset_default_balance_cache_clears_singleton(monkeypatch) -> None:
    reset_default_balance_cache()
    monkeypatch.setattr(
        "app.core.redis.get_redis", lambda: FakeRedis(), raising=True
    )
    first = get_default_balance_cache()
    reset_default_balance_cache()
    monkeypatch.setattr(
        "app.core.redis.get_redis", lambda: FakeRedis(), raising=True
    )
    second = get_default_balance_cache()
    try:
        assert first is not second
    finally:
        reset_default_balance_cache()
