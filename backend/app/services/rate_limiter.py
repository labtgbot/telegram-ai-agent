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

Redis executes the check-and-record path as one Lua script: prune stale
entries, count every bucket, and conditionally record the new event
without yielding to competing clients between the check and the write.
"""
from __future__ import annotations

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

    async def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any: ...


# ------------------------------------------------------------- key & helpers

_KEY_PREFIX = "rl"


def _bucket_key(plan: str, identifier: str, quota_key: str) -> str:
    return f"{_KEY_PREFIX}:{plan}:{identifier}:{quota_key}"


def _now_ms() -> int:
    return int(time.time() * 1000)


_ATOMIC_EVALUATE_SCRIPT = """
local now_ms = tonumber(ARGV[1])
local record = tonumber(ARGV[2])
local member = ARGV[3]
local bucket_count = #KEYS

local counts = {}
local limits = {}
local windows = {}

local function seconds_until(reset_ms)
    local delta = reset_ms - now_ms
    if delta < 0 then
        delta = 0
    end
    return math.ceil(delta / 1000)
end

local function bucket_reset_after(index)
    if counts[index] <= 0 then
        return 0
    end
    local oldest = redis.call("ZRANGE", KEYS[index], 0, 0, "WITHSCORES")
    if oldest[2] == nil then
        return 0
    end
    local reset_ms = tonumber(oldest[2]) + (windows[index] * 1000)
    return seconds_until(reset_ms)
end

local tightest_index = 1
local tightest_remaining = nil
local tightest_window = 0

for i = 1, bucket_count do
    local arg_offset = 4 + ((i - 1) * 2)
    local limit = tonumber(ARGV[arg_offset])
    local window_seconds = tonumber(ARGV[arg_offset + 1])
    local min_score = now_ms - (window_seconds * 1000)

    redis.call("ZREMRANGEBYSCORE", KEYS[i], 0, min_score)
    local count = tonumber(redis.call("ZCARD", KEYS[i]))

    counts[i] = count
    limits[i] = limit
    windows[i] = window_seconds

    local remaining = limit - count
    local is_tighter = false
    if tightest_remaining == nil then
        is_tighter = true
    elseif remaining < tightest_remaining then
        is_tighter = true
    elseif remaining == tightest_remaining and window_seconds > tightest_window then
        is_tighter = true
    end

    if is_tighter then
        tightest_index = i
        tightest_remaining = remaining
        tightest_window = window_seconds
    end
end

for i = 1, bucket_count do
    if counts[i] >= limits[i] then
        local reset_after = bucket_reset_after(i)
        local retry_after = reset_after
        if retry_after < 1 then
            retry_after = 1
        end
        return {0, i, counts[i], 0, reset_after, retry_after}
    end
end

if record == 1 then
    for i = 1, bucket_count do
        redis.call("ZADD", KEYS[i], now_ms, member)
        redis.call("EXPIRE", KEYS[i], windows[i])
    end
end

local remaining = limits[tightest_index] - counts[tightest_index]
if record == 1 then
    remaining = remaining - 1
end
if remaining < 0 then
    remaining = 0
end

local reset_after = 0
if counts[tightest_index] > 0 then
    reset_after = bucket_reset_after(tightest_index)
elseif record == 1 then
    reset_after = windows[tightest_index]
end

return {1, tightest_index, counts[tightest_index], remaining, reset_after, 0}
"""


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

        keys = [self._key(plan, identifier, quota_key) for quota_key, _rule in rules]
        # ZSET members must be unique; without entropy two calls within
        # the same millisecond would collapse into one entry and let
        # callers bypass the quota.
        member = f"{now_ms}:{secrets.token_hex(6)}" if record else ""
        args: list[Any] = [now_ms, 1 if record else 0, member]
        for _quota_key, rule in rules:
            args.extend([rule.limit, rule.window_seconds])

        raw = await self._redis.eval(
            _ATOMIC_EVALUATE_SCRIPT,
            len(keys),
            *keys,
            *args,
        )
        allowed = bool(int(raw[0]))
        rule_index = int(raw[1]) - 1
        count = int(raw[2])
        remaining = int(raw[3])
        reset_after = int(raw[4])
        retry_after = int(raw[5])
        quota_key, rule = rules[rule_index]

        if not allowed:
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
                    reset_after=reset_after,
                )
            return RateLimitResult(
                allowed=False,
                plan=plan,
                action=action,
                quota_key=quota_key,
                limit=rule.limit,
                remaining=0,
                reset_after=reset_after,
                retry_after=retry_after,
            )

        return RateLimitResult(
            allowed=True,
            plan=plan,
            action=action,
            quota_key=quota_key,
            limit=rule.limit,
            remaining=remaining,
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
