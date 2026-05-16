"""Sliding-window-log rate limiter backed by Redis.

Implements ADR-0004: every billable action records its timestamp in a
Redis sorted set keyed by ``rl:{plan}:{identifier}:{quota_key}``. Before
checking the count we evict elements older than the window — the count
of what remains is the effective usage.

The limiter consumes :class:`RateLimitConfig` (see
``app.services.rate_limit_config``) so quotas can be tuned at runtime
through ``admin_settings.rate_limits`` without a redeploy.

Each call to :meth:`RateLimiter.consume` enforces *every* quota that
applies to the action (hourly + daily + media-specific). The most
restrictive one wins; on the happy path we ZADD the timestamp into all
relevant buckets atomically so a future "expensive" bucket can't be
bypassed by hitting it before the cheaper ones.

The Redis interaction is intentionally pure pipeline / WATCH-free.
That keeps the implementation testable against in-memory doubles and
robust if the operator switches Redis backends (e.g. KeyDB). The cost
is two round trips per check (peek then conditional commit), which is
well below the < 1 ms p95 target from ADR-0004.
"""
from __future__ import annotations

import math
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.subscription import Subscription
from app.models.user import User
from app.services.payment_packages import PRO_PLAN_CODE
from app.services.rate_limit_config import (
    ACTION_DEFAULT,
    PLAN_ANONYMOUS,
    PLAN_FREE,
    PLAN_PREMIUM,
    PLAN_PRO,
    RateLimitConfig,
    RateLimitRule,
)

logger = get_logger(__name__)


# ----------------------------------------------------------------- exceptions


class RateLimiterError(Exception):
    """Base class for rate-limiter failures."""


class RateLimitedError(RateLimiterError):
    """Raised when the caller exceeded the active quota.

    Carries the data the HTTP layer (and the bot) needs to render a
    helpful response: the offending bucket, its limit, when it resets,
    and the recommended Retry-After value.
    """

    def __init__(
        self,
        *,
        plan: str,
        action: str,
        quota_key: str,
        limit: int,
        retry_after: int,
        reset_after: int,
    ) -> None:
        super().__init__(
            f"rate-limited plan={plan} action={action} quota={quota_key} "
            f"limit={limit} retry_after={retry_after}"
        )
        self.plan = plan
        self.action = action
        self.quota_key = quota_key
        self.limit = limit
        self.retry_after = retry_after
        self.reset_after = reset_after


# ------------------------------------------------------------------- results


@dataclass(frozen=True)
class RateLimitResult:
    """Outcome of a single :meth:`RateLimiter.consume` call.

    ``quota_key`` / ``limit`` / ``remaining`` reflect the *tightest*
    bucket — the one closest to exhaustion — so the HTTP layer can
    surface meaningful ``X-RateLimit-*`` headers without knowing about
    every applicable quota.
    """

    allowed: bool
    plan: str
    action: str
    quota_key: str
    limit: int
    remaining: int
    reset_after: int
    retry_after: int


# ------------------------------------------------------------------- protocol


class _AsyncRedisLike(Protocol):
    """Structural subset of ``redis.asyncio.Redis`` the limiter uses.

    Loosely typed so the real client and lightweight in-memory test
    doubles both satisfy it.
    """

    def pipeline(self, transaction: bool = ...) -> Any: ...
    async def zrange(
        self,
        name: Any,
        start: Any,
        end: Any,
        *,
        withscores: bool = ...,
    ) -> Any: ...


# ------------------------------------------------------------- key & helpers

_KEY_PREFIX = "rl"


def _bucket_key(plan: str, identifier: str, quota_key: str) -> str:
    return f"{_KEY_PREFIX}:{plan}:{identifier}:{quota_key}"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _seconds_until(reset_ms: int, now_ms: int) -> int:
    """Round up to the nearest second so Retry-After never under-reports."""
    delta = max(0, reset_ms - now_ms)
    return int(math.ceil(delta / 1000.0))


# ------------------------------------------------------------- plan resolver


def resolve_plan(
    user: User | None,
    *,
    active_subscriptions: list[Subscription] | None = None,
) -> str:
    """Pick the canonical plan code for ``user``.

    Resolution order:

    1. No user → :data:`PLAN_ANONYMOUS`.
    2. An active subscription with ``plan_code == "pro"`` → :data:`PLAN_PRO`.
    3. ``user.is_premium`` is true → :data:`PLAN_PREMIUM`.
    4. Otherwise → :data:`PLAN_FREE`.

    ``active_subscriptions`` is optional — supply it when the caller has
    already loaded the relation to avoid an extra query.
    """
    if user is None:
        return PLAN_ANONYMOUS
    if active_subscriptions:
        for sub in active_subscriptions:
            if (
                sub.plan_code == PRO_PLAN_CODE
                and (sub.status or "").lower() == "active"
            ):
                return PLAN_PRO
    if user.is_premium:
        return PLAN_PREMIUM
    return PLAN_FREE


async def resolve_plan_for_user(
    session: AsyncSession,
    user: User | None,
) -> str:
    """Same as :func:`resolve_plan` but loads active subscriptions itself."""
    if user is None:
        return PLAN_ANONYMOUS
    stmt = (
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .where(Subscription.status == "active")
    )
    subs = list((await session.execute(stmt)).scalars().all())
    return resolve_plan(user, active_subscriptions=subs)


# --------------------------------------------------------------- the limiter


class RateLimiter:
    """Sliding-window-log limiter.

    The instance is cheap to build — keep one per request or per worker.
    ``config`` is a snapshot of the active rules; reload it (via
    :func:`app.services.rate_limit_config.load_rate_limits`) when admin
    settings change.
    """

    def __init__(
        self,
        redis: Any,
        config: RateLimitConfig,
        *,
        key_prefix: str = _KEY_PREFIX,
    ) -> None:
        self._redis = redis
        self._config = config
        self._key_prefix = key_prefix

    def _key(self, plan: str, identifier: str, quota_key: str) -> str:
        return f"{self._key_prefix}:{plan}:{identifier}:{quota_key}"

    # ----- public API ----------------------------------------------------

    async def peek(
        self,
        *,
        plan: str,
        identifier: str,
        action: str = ACTION_DEFAULT,
    ) -> RateLimitResult:
        """Return current usage without recording a new event.

        Useful for "would this be allowed?" probes and for surfacing
        ``X-RateLimit-*`` headers on responses that aren't billable.
        """
        rules = self._config.rules_for(plan, action)
        return await self._evaluate(
            plan=plan,
            identifier=identifier,
            action=action,
            rules=rules,
            now_ms=_now_ms(),
            record=False,
        )

    async def consume(
        self,
        *,
        plan: str,
        identifier: str,
        action: str = ACTION_DEFAULT,
    ) -> RateLimitResult:
        """Record an event after confirming every quota still has headroom.

        Raises:
            RateLimitedError: At least one quota is exhausted. No event
                is recorded in this case (no quota is consumed).
        """
        rules = self._config.rules_for(plan, action)
        return await self._evaluate(
            plan=plan,
            identifier=identifier,
            action=action,
            rules=rules,
            now_ms=_now_ms(),
            record=True,
        )

    # ----- core logic ----------------------------------------------------

    async def _evaluate(
        self,
        *,
        plan: str,
        identifier: str,
        action: str,
        rules: list[tuple[str, RateLimitRule]],
        now_ms: int,
        record: bool,
    ) -> RateLimitResult:
        if not rules:
            # No quotas defined for this (plan, action) — treat as allowed
            # with effectively unlimited headroom. We still need a quota
            # key for the result shape; use the synthetic "none" marker
            # so the HTTP layer can decide whether to emit headers.
            return RateLimitResult(
                allowed=True,
                plan=plan,
                action=action,
                quota_key="none",
                limit=0,
                remaining=0,
                reset_after=0,
                retry_after=0,
            )

        # Round 1: peek each bucket via a single pipeline. We need both
        # the post-eviction count and the oldest surviving timestamp
        # (the latter drives Retry-After when we're over the limit).
        pipe = self._redis.pipeline(transaction=False)
        keys: list[str] = []
        for quota_key, rule in rules:
            key = self._key(plan, identifier, quota_key)
            keys.append(key)
            window_ms = rule.window_seconds * 1000
            min_score = now_ms - window_ms
            # 1) drop expired entries, 2) count what remains.
            pipe.zremrangebyscore(key, 0, min_score)
            pipe.zcard(key)
        raw = await pipe.execute()

        # raw layout: for each rule we get 2 entries (zremrangebyscore, zcard).
        peeks: list[tuple[str, RateLimitRule, str, int]] = []
        for idx, (quota_key, rule) in enumerate(rules):
            count = int(raw[idx * 2 + 1] or 0)
            peeks.append((quota_key, rule, keys[idx], count))

        # Identify the tightest bucket — smallest remaining slots wins,
        # with the longest window breaking ties so daily caps surface
        # before hourly ones when both have the same headroom.
        tightest = min(
            peeks,
            key=lambda p: (p[1].limit - p[3], -p[1].window_seconds),
        )
        t_quota_key, t_rule, t_key, t_count = tightest
        remaining = max(0, t_rule.limit - t_count)

        # Find the oldest surviving timestamp to compute reset_after for
        # whichever bucket is closest to capacity. We only need this for
        # the tightest bucket.
        reset_after = 0
        if t_count > 0:
            oldest = await self._redis.zrange(t_key, 0, 0, withscores=True)
            if oldest:
                _, oldest_score = oldest[0]
                reset_ms = int(oldest_score) + t_rule.window_seconds * 1000
                reset_after = _seconds_until(reset_ms, now_ms)

        # Check every bucket for breach (not just the tightest — a less
        # tight bucket could still be over its limit when limits change).
        for quota_key, rule, key, count in peeks:
            if count >= rule.limit:
                # Find when this bucket resets.
                oldest = await self._redis.zrange(key, 0, 0, withscores=True)
                bucket_reset = 0
                if oldest:
                    _, oldest_score = oldest[0]
                    reset_ms = int(oldest_score) + rule.window_seconds * 1000
                    bucket_reset = _seconds_until(reset_ms, now_ms)
                # Retry-After is the most permissive (shortest) wait that
                # would unblock the caller for *this* bucket. Use at
                # least one second so clients don't hot-loop.
                retry_after = max(1, bucket_reset)
                logger.info(
                    "rate_limit.blocked",
                    plan=plan,
                    action=action,
                    quota=quota_key,
                    limit=rule.limit,
                    count=count,
                    retry_after=retry_after,
                )
                if record:
                    raise RateLimitedError(
                        plan=plan,
                        action=action,
                        quota_key=quota_key,
                        limit=rule.limit,
                        retry_after=retry_after,
                        reset_after=bucket_reset,
                    )
                return RateLimitResult(
                    allowed=False,
                    plan=plan,
                    action=action,
                    quota_key=quota_key,
                    limit=rule.limit,
                    remaining=0,
                    reset_after=bucket_reset,
                    retry_after=retry_after,
                )

        if not record:
            return RateLimitResult(
                allowed=True,
                plan=plan,
                action=action,
                quota_key=t_quota_key,
                limit=t_rule.limit,
                remaining=remaining,
                reset_after=reset_after,
                retry_after=0,
            )

        # Round 2: every bucket still has headroom — record the event.
        # ZSET members must be unique; without entropy two calls within
        # the same millisecond would collapse into one entry and let
        # callers bypass the quota.
        member = f"{now_ms}:{secrets.token_hex(6)}"
        pipe = self._redis.pipeline(transaction=True)
        for _quota_key, rule, key, _count in peeks:
            pipe.zadd(key, {member: now_ms})
            # TTL = window so empty buckets evict themselves automatically.
            pipe.expire(key, rule.window_seconds)
        await pipe.execute()

        # After recording, the tightest bucket has one more entry.
        new_remaining = max(0, remaining - 1)
        if t_count + 1 >= 1 and reset_after == 0:
            # If we just inserted the first item, the bucket resets a
            # full window from now.
            reset_after = t_rule.window_seconds
        return RateLimitResult(
            allowed=True,
            plan=plan,
            action=action,
            quota_key=t_quota_key,
            limit=t_rule.limit,
            remaining=new_remaining,
            reset_after=reset_after,
            retry_after=0,
        )


__all__ = [
    "PLAN_ANONYMOUS",
    "PLAN_FREE",
    "PLAN_PREMIUM",
    "PLAN_PRO",
    "RateLimitResult",
    "RateLimitedError",
    "RateLimiter",
    "RateLimiterError",
    "resolve_plan",
    "resolve_plan_for_user",
]
