"""Redis-backed cache for ``users.token_balance``.

``GET /api/v1/user/balance`` and the rate-limit middleware both read the
balance on every authenticated request, so the row easily dominates the
DB read budget. Caching it in Redis with a write-through pattern brings
the hot path off PostgreSQL while keeping correctness guarantees:

* on read miss we hydrate the cache from ``users.token_balance``;
* on every token mutation (``TokenService.add`` / ``spend`` / ``refund``
  / ``manual_bonus``) we explicitly :func:`invalidate` the key — the
  cache is read-only relative to the DB ledger, so an empty cache always
  forces a fresh read;
* :func:`set_balance` is exposed for code paths that already know the
  new balance (e.g. just-committed transactions) and want to skip the
  next read entirely.

The keyspace lives at ``balance:user:{user_id}`` to match the
``rl:`` / ``daily_bonus:`` conventions used elsewhere in the codebase.
TTL comes from :attr:`Settings.balance_cache_ttl_seconds` and acts as a
safety net — explicit invalidation is the primary correctness mechanism.

Issue #36 acceptance criteria: *кэширование баланса в Redis
(write-through + invalidation)*.
"""
from __future__ import annotations

from typing import Protocol, cast

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


KEY_PREFIX = "balance:user:"


class _RedisLike(Protocol):
    """Minimal subset of :class:`redis.asyncio.Redis` we use."""

    async def get(self, name: str) -> str | bytes | None: ...

    async def set(
        self, name: str, value: str | int, ex: int | None = ...
    ) -> object: ...

    async def delete(self, *names: str) -> int: ...


def cache_key(user_id: int) -> str:
    """Return the Redis key used to cache ``user_id``'s balance."""
    return f"{KEY_PREFIX}{int(user_id)}"


class BalanceCache:
    """Thin wrapper around Redis providing write-through balance caching.

    The class is intentionally tiny — all the real work (deciding when
    to refresh, plumbing the DB read) belongs in :class:`TokenService`.
    Keeping the cache focused makes it trivial to mock in tests and to
    swap the backend (e.g. Dragonfly, KeyDB) without touching callers.
    """

    def __init__(
        self,
        redis: _RedisLike,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        self._redis = redis
        ttl = ttl_seconds if ttl_seconds is not None else get_settings().balance_cache_ttl_seconds
        # Clamp to >=1s so set() never collapses into a no-op delete.
        self._ttl = max(int(ttl), 1)

    @property
    def ttl_seconds(self) -> int:
        return self._ttl

    async def get(self, user_id: int) -> int | None:
        """Return the cached balance or ``None`` on miss."""
        raw = await self._redis.get(cache_key(user_id))
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            # Corrupted value — drop it and force a refresh.
            logger.warning(
                "balance_cache.corrupt_value",
                user_id=user_id,
                value=str(raw)[:32],
            )
            await self.invalidate(user_id)
            return None

    async def set(self, user_id: int, balance: int) -> None:
        """Write ``balance`` to the cache under the configured TTL."""
        await self._redis.set(cache_key(user_id), int(balance), ex=self._ttl)

    async def invalidate(self, user_id: int) -> None:
        """Drop the cached value so the next read hits the DB."""
        await self._redis.delete(cache_key(user_id))

    async def invalidate_many(self, user_ids: list[int]) -> None:
        """Bulk-invalidate; useful for admin tools that touch many users."""
        if not user_ids:
            return
        keys = [cache_key(uid) for uid in user_ids]
        await self._redis.delete(*keys)


_default_cache: BalanceCache | None = None


def get_default_balance_cache() -> BalanceCache:
    """Return the process-wide :class:`BalanceCache` singleton.

    Production call sites (``GET /api/v1/user/balance``, the generation
    services, ``payments``, …) use this helper so the cache layer is
    wired without threading an extra dependency through every
    constructor. The Redis client itself is the lazy singleton from
    :func:`app.core.redis.get_redis`, so importing this module has no
    network side effects.

    Tests that build :class:`TokenService` directly with only a session
    bypass this helper entirely, preserving the existing fixture style.
    """
    global _default_cache
    if _default_cache is None:
        from app.core.redis import get_redis

        # ``redis.asyncio.Redis`` advertises wider key types (``bytes |
        # str | memoryview``) and a ``Awaitable | Any`` return union
        # that does not structurally match our narrow ``_RedisLike``
        # protocol. The runtime contract holds — just satisfy mypy.
        _default_cache = BalanceCache(cast("_RedisLike", get_redis()))
    return _default_cache


def reset_default_balance_cache() -> None:
    """Drop the cached singleton (test helper / app shutdown)."""
    global _default_cache
    _default_cache = None


__all__ = [
    "BalanceCache",
    "KEY_PREFIX",
    "cache_key",
    "get_default_balance_cache",
    "reset_default_balance_cache",
]
