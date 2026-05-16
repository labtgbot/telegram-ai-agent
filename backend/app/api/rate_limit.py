"""FastAPI integration for the sliding-window rate limiter.

Provides:

* :func:`get_rate_limiter` — request-scoped factory that loads the
  current config and returns a fresh :class:`RateLimiter` bound to the
  shared Redis client. Cheap to call: only the admin-settings row is
  fetched per request.
* :func:`rate_limit` — dependency factory. Use it on heavy AI endpoints:

  .. code-block:: python

      @router.post(
          "/generate-image",
          dependencies=[Depends(rate_limit(action="image"))],
      )
      async def generate_image(...): ...

  On breach the dependency raises an :class:`HTTPException` 429 with
  ``Retry-After`` and ``X-RateLimit-*`` headers populated. On pass, the
  same headers are attached to the success response via
  ``response.headers`` so the Mini App can display remaining quota.

The dependency resolves the caller's plan from ``request.state.user``
(set by ``get_current_user_from_init_data``) or — if absent — falls
back to the anonymous bucket keyed by client IP.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response, status

from app.auth.dependencies import SessionDep
from app.core.logging import get_logger
from app.core.redis import get_redis
from app.models.user import User
from app.services.rate_limit_config import (
    ACTION_DEFAULT,
    KNOWN_ACTIONS,
    load_rate_limits,
)
from app.services.rate_limiter import (
    PLAN_ANONYMOUS,
    RateLimitedError,
    RateLimiter,
    RateLimitResult,
    resolve_plan_for_user,
)

logger = get_logger(__name__)


async def get_rate_limiter(session: SessionDep) -> RateLimiter:
    """Build a :class:`RateLimiter` for the current request.

    The Redis client is the process-wide singleton from
    :func:`app.core.redis.get_redis`. Config is reloaded per request so
    admin edits propagate without a redeploy — the read is one indexed
    lookup against ``admin_settings`` and is cheap.
    """
    config = await load_rate_limits(session)
    return RateLimiter(get_redis(), config)


RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def _client_ip(request: Request) -> str:
    """Best-effort client IP, used as the anonymous-bucket identifier.

    Honours ``X-Forwarded-For`` (first hop) when present — the deployment
    notes describe nginx/Cloudflare in front of the app — and falls back
    to the direct peer address. Returns ``"unknown"`` if neither is
    available (test clients).
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        head = fwd.split(",", 1)[0].strip()
        if head:
            return head
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _attach_headers(response: Response, result: RateLimitResult) -> None:
    """Populate the ``X-RateLimit-*`` response headers.

    Quota of 0 (the synthetic "none" sentinel) is skipped so unknown
    actions don't pollute responses with zeros.
    """
    if result.limit <= 0:
        return
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    response.headers["X-RateLimit-Reset"] = str(result.reset_after)
    response.headers["X-RateLimit-Quota"] = result.quota_key


def rate_limit(
    *,
    action: str = ACTION_DEFAULT,
) -> Callable[..., object]:
    """Build a FastAPI dependency enforcing a per-plan quota.

    Parameters:
        action: One of :data:`KNOWN_ACTIONS`. Defaults to ``"default"``
            which only enforces the universal hourly/daily caps.

    The dependency uses ``request.state.user`` when present (set by the
    Telegram init-data auth dependency) for the identifier; anonymous
    callers are bucketed by client IP.
    """
    if action not in KNOWN_ACTIONS:
        raise ValueError(f"unknown rate-limit action: {action!r}")

    async def _dep(
        request: Request,
        response: Response,
        limiter: RateLimiterDep,
        session: SessionDep,
    ) -> RateLimitResult:
        user: User | None = getattr(request.state, "user", None)
        if user is not None:
            plan = await resolve_plan_for_user(session, user)
            identifier = str(user.telegram_id)
        else:
            plan = PLAN_ANONYMOUS
            identifier = f"ip:{_client_ip(request)}"

        try:
            result = await limiter.consume(
                plan=plan,
                identifier=identifier,
                action=action,
            )
        except RateLimitedError as exc:
            headers = {
                "Retry-After": str(exc.retry_after),
                "X-RateLimit-Limit": str(exc.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": str(exc.reset_after),
                "X-RateLimit-Quota": exc.quota_key,
            }
            logger.info(
                "rate_limit.http_429",
                plan=plan,
                action=action,
                quota=exc.quota_key,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limited",
                    "plan": plan,
                    "action": action,
                    "quota": exc.quota_key,
                    "limit": exc.limit,
                    "retry_after": exc.retry_after,
                },
                headers=headers,
            ) from exc

        _attach_headers(response, result)
        return result

    return _dep


__all__ = [
    "RateLimiterDep",
    "get_rate_limiter",
    "rate_limit",
]
