"""Unit tests for :mod:`app.services.rate_limiter`.

These tests run entirely in-process: the limiter only needs the subset
of the Redis API listed in ``_AsyncRedisLike``, so a small fake suffices.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from app.services.rate_limit_config import (
    ACTION_IMAGE,
    PLAN_ANONYMOUS,
    PLAN_FREE,
    PLAN_PREMIUM,
    PLAN_PRO,
    RateLimitConfig,
    RateLimitRule,
)
from app.services.rate_limiter import (
    RateLimitedError,
    RateLimiter,
    resolve_plan,
)

# ----------------------------------------------------------------- fake redis


class _FakeZSet:
    """Minimal sorted-set implementation backing :class:`FakeRedis`."""

    def __init__(self) -> None:
        self.items: dict[str, float] = {}

    def add(self, mapping: dict[str, float]) -> None:
        self.items.update(mapping)

    def remrangebyscore(self, min_score: float, max_score: float) -> int:
        removed = [
            m for m, s in self.items.items() if min_score <= s <= max_score
        ]
        for m in removed:
            del self.items[m]
        return len(removed)

    def card(self) -> int:
        return len(self.items)

    def range(self, start: int, end: int, withscores: bool) -> list[Any]:
        ordered = sorted(self.items.items(), key=lambda kv: kv[1])
        slice_ = ordered[start:] if end == -1 else ordered[start : end + 1]
        if withscores:
            return [(m, s) for m, s in slice_]
        return [m for m, _ in slice_]


class _PipelineOp:
    def __init__(self, op: str, key: str, args: tuple[Any, ...]) -> None:
        self.op = op
        self.key = key
        self.args = args


class _FakePipeline:
    def __init__(self, store: FakeRedis, *, transaction: bool) -> None:
        self.store = store
        self.transaction = transaction
        self.ops: list[_PipelineOp] = []

    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        self.ops.append(_PipelineOp("zremrangebyscore", key, (min_score, max_score)))

    def zcard(self, key: str) -> None:
        self.ops.append(_PipelineOp("zcard", key, ()))

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        self.ops.append(_PipelineOp("zadd", key, (mapping,)))

    def expire(self, key: str, seconds: int) -> None:
        self.ops.append(_PipelineOp("expire", key, (seconds,)))

    async def execute(self) -> list[Any]:
        results: list[Any] = []
        for op in self.ops:
            results.append(self.store._apply(op))
        return results


class FakeRedis:
    """In-memory async-compatible substitute for :class:`redis.asyncio.Redis`.

    Implements only the subset the limiter touches: ``pipeline``,
    ``zrange``, and the ops the pipeline queues.
    """

    def __init__(self) -> None:
        self.sets: dict[str, _FakeZSet] = {}
        self.expirations: dict[str, int] = {}

    def _get(self, key: str) -> _FakeZSet:
        if key not in self.sets:
            self.sets[key] = _FakeZSet()
        return self.sets[key]

    def _apply(self, op: _PipelineOp) -> Any:
        zset = self._get(op.key)
        if op.op == "zremrangebyscore":
            min_score, max_score = op.args
            return zset.remrangebyscore(min_score, max_score)
        if op.op == "zcard":
            return zset.card()
        if op.op == "zadd":
            mapping = op.args[0]
            zset.add(mapping)
            return len(mapping)
        if op.op == "expire":
            seconds = op.args[0]
            self.expirations[op.key] = seconds
            return True
        raise AssertionError(f"unknown op: {op.op}")

    def pipeline(self, transaction: bool = False) -> _FakePipeline:
        return _FakePipeline(self, transaction=transaction)

    async def zrange(
        self,
        key: str,
        start: int,
        end: int,
        *,
        withscores: bool = False,
    ) -> list[Any]:
        return self._get(key).range(start, end, withscores)


# ----------------------------------------------------------------- helpers


def _config(rules: dict[str, dict[str, RateLimitRule]]) -> RateLimitConfig:
    return RateLimitConfig(plans=rules)


def _hourly(limit: int) -> RateLimitRule:
    return RateLimitRule(limit=limit, window_seconds=3600)


def _daily(limit: int) -> RateLimitRule:
    return RateLimitRule(limit=limit, window_seconds=86400)


# ----------------------------------------------------------------- consume — pass


@pytest.mark.asyncio
async def test_consume_allows_first_request() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config({PLAN_FREE: {"per_hour": _hourly(5)}}),
    )
    result = await limiter.consume(plan=PLAN_FREE, identifier="42")
    assert result.allowed is True
    assert result.limit == 5
    assert result.remaining == 4
    assert result.quota_key == "per_hour"
    assert result.retry_after == 0


@pytest.mark.asyncio
async def test_consume_counts_each_request() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config({PLAN_FREE: {"per_hour": _hourly(3)}}),
    )
    for expected_remaining in (2, 1, 0):
        result = await limiter.consume(plan=PLAN_FREE, identifier="9")
        assert result.allowed is True
        assert result.remaining == expected_remaining


@pytest.mark.asyncio
async def test_consume_buckets_users_separately() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config({PLAN_FREE: {"per_hour": _hourly(2)}}),
    )
    await limiter.consume(plan=PLAN_FREE, identifier="alice")
    await limiter.consume(plan=PLAN_FREE, identifier="alice")
    # Alice is full but Bob is fresh.
    result = await limiter.consume(plan=PLAN_FREE, identifier="bob")
    assert result.allowed is True
    assert result.remaining == 1


# ----------------------------------------------------------------- consume — exceed


@pytest.mark.asyncio
async def test_consume_raises_when_quota_exhausted() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config({PLAN_FREE: {"per_hour": _hourly(2)}}),
    )
    await limiter.consume(plan=PLAN_FREE, identifier="1")
    await limiter.consume(plan=PLAN_FREE, identifier="1")
    with pytest.raises(RateLimitedError) as excinfo:
        await limiter.consume(plan=PLAN_FREE, identifier="1")
    err = excinfo.value
    assert err.plan == PLAN_FREE
    assert err.quota_key == "per_hour"
    assert err.limit == 2
    assert err.retry_after >= 1


@pytest.mark.asyncio
async def test_consume_does_not_record_when_blocked() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config({PLAN_FREE: {"per_hour": _hourly(1)}}),
    )
    await limiter.consume(plan=PLAN_FREE, identifier="1")
    with pytest.raises(RateLimitedError):
        await limiter.consume(plan=PLAN_FREE, identifier="1")
    # Bucket should still only have the single original entry — the
    # rejected call must not pad the count.
    key = "rl:free:1:per_hour"
    assert redis._get(key).card() == 1


@pytest.mark.asyncio
async def test_consume_blocks_on_image_quota_even_when_hourly_has_room() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config(
            {
                PLAN_FREE: {
                    "per_hour": _hourly(100),
                    "per_day": _daily(100),
                    "image_per_day": _daily(2),
                }
            }
        ),
    )
    await limiter.consume(plan=PLAN_FREE, identifier="1", action=ACTION_IMAGE)
    await limiter.consume(plan=PLAN_FREE, identifier="1", action=ACTION_IMAGE)
    with pytest.raises(RateLimitedError) as excinfo:
        await limiter.consume(plan=PLAN_FREE, identifier="1", action=ACTION_IMAGE)
    assert excinfo.value.quota_key == "image_per_day"


@pytest.mark.asyncio
async def test_remaining_tracks_tightest_bucket() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config(
            {
                PLAN_FREE: {
                    "per_hour": _hourly(100),
                    "image_per_day": _daily(3),
                }
            }
        ),
    )
    result = await limiter.consume(
        plan=PLAN_FREE, identifier="1", action=ACTION_IMAGE
    )
    # image_per_day=3 is tighter than per_hour=100, so remaining tracks it.
    assert result.quota_key == "image_per_day"
    assert result.remaining == 2


# ----------------------------------------------------------------- window reset


@pytest.mark.asyncio
async def test_window_reset_clears_expired_entries() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config({PLAN_FREE: {"per_hour": _hourly(2)}}),
    )
    key = "rl:free:7:per_hour"
    # Simulate two events from > 1 hour ago.
    redis._get(key).items["old-1"] = 0.0
    redis._get(key).items["old-2"] = 1.0
    # The next consume must succeed because eviction drops them first.
    result = await limiter.consume(plan=PLAN_FREE, identifier="7")
    assert result.allowed is True
    # And the stale entries are gone.
    assert all(score > 1000 for score in redis._get(key).items.values())


@pytest.mark.asyncio
async def test_retry_after_reflects_oldest_entry() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config({PLAN_FREE: {"per_hour": _hourly(1)}}),
    )
    await limiter.consume(plan=PLAN_FREE, identifier="3")
    with pytest.raises(RateLimitedError) as excinfo:
        await limiter.consume(plan=PLAN_FREE, identifier="3")
    # Window is 1 hour, so retry-after must be close to (but not exceed) 3600.
    assert 1 <= excinfo.value.retry_after <= 3600


# ----------------------------------------------------------------- peek


@pytest.mark.asyncio
async def test_peek_does_not_consume() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config({PLAN_FREE: {"per_hour": _hourly(2)}}),
    )
    first = await limiter.peek(plan=PLAN_FREE, identifier="44")
    second = await limiter.peek(plan=PLAN_FREE, identifier="44")
    assert first.allowed and second.allowed
    assert first.remaining == 2
    assert second.remaining == 2  # peek must not have consumed anything


@pytest.mark.asyncio
async def test_peek_reports_blocked_without_raising() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(
        redis,
        _config({PLAN_FREE: {"per_hour": _hourly(1)}}),
    )
    await limiter.consume(plan=PLAN_FREE, identifier="44")
    result = await limiter.peek(plan=PLAN_FREE, identifier="44")
    assert result.allowed is False
    assert result.remaining == 0
    assert result.retry_after >= 1


# ----------------------------------------------------------------- empty config


@pytest.mark.asyncio
async def test_consume_with_no_rules_is_allowed() -> None:
    redis = FakeRedis()
    limiter = RateLimiter(redis, _config({}))
    result = await limiter.consume(plan="phantom", identifier="anyone")
    assert result.allowed is True
    assert result.limit == 0
    assert result.quota_key == "none"


# ----------------------------------------------------------------- resolve_plan


@dataclass
class _FakeUser:
    id: int = 1
    is_premium: bool = False


@dataclass
class _FakeSub:
    plan_code: str = "pro"
    status: str = "active"


def test_resolve_plan_anonymous_for_no_user() -> None:
    assert resolve_plan(None) == PLAN_ANONYMOUS


def test_resolve_plan_free_by_default() -> None:
    assert resolve_plan(_FakeUser()) == PLAN_FREE  # type: ignore[arg-type]


def test_resolve_plan_premium_when_flag_set() -> None:
    assert resolve_plan(_FakeUser(is_premium=True)) == PLAN_PREMIUM  # type: ignore[arg-type]


def test_resolve_plan_pro_when_active_subscription() -> None:
    user = _FakeUser(is_premium=True)
    sub = _FakeSub()
    assert (
        resolve_plan(user, active_subscriptions=[sub])  # type: ignore[arg-type]
        == PLAN_PRO
    )


def test_resolve_plan_ignores_inactive_subscription() -> None:
    user = _FakeUser(is_premium=True)
    sub = _FakeSub(status="cancelled")
    assert (
        resolve_plan(user, active_subscriptions=[sub])  # type: ignore[arg-type]
        == PLAN_PREMIUM
    )
