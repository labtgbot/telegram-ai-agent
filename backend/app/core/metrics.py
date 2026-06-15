"""Prometheus metrics for the FastAPI backend.

HTTP-level metrics (requests total, latency histogram, in-flight requests) are
emitted by a small local middleware so the runtime does not depend on a
Starlette-version-pinned instrumentation wrapper. This module also adds the
*business* metrics referenced in the Phase 4 SLO catalogue:

* ``tokens_sold_total`` — counter of tokens credited by completed purchases.
* ``tokens_spent_total`` — counter of tokens debited by spends, labelled by service.
* ``revenue_stars_total`` / ``revenue_usd_total`` — gross revenue counters.
* ``active_users`` — gauge tracking the unique users that hit an instrumented
  endpoint inside :pyattr:`Settings.metrics_active_user_window_seconds`.
* ``payment_events_total`` — counter of payment lifecycle events
  (created/completed/duplicate/failed).
* ``composio_timeout_without_response_total`` — Composio execute calls that
  timed out without a provider response and were deliberately not retried.

The module is intentionally side-effect-free at import time: nothing is
registered globally, the metric objects live in a single ``REGISTRY`` so tests
can clear it between runs.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------- registry

# Dedicated registry keeps our metrics separate from the default global
# registry — important for tests that want to reset state without nuking
# every collector that lives in ``prometheus_client.REGISTRY``.
REGISTRY: CollectorRegistry = CollectorRegistry()

NAMESPACE = "tgai"
SUBSYSTEM_BUSINESS = "business"
SUBSYSTEM_PROVIDER = "provider"


tokens_sold_total: Counter = Counter(
    name="tokens_sold_total",
    documentation="Total tokens credited to users via completed purchases.",
    labelnames=("package",),
    namespace=NAMESPACE,
    subsystem=SUBSYSTEM_BUSINESS,
    registry=REGISTRY,
)

tokens_spent_total: Counter = Counter(
    name="tokens_spent_total",
    documentation="Total tokens debited from users by spend operations.",
    labelnames=("service",),
    namespace=NAMESPACE,
    subsystem=SUBSYSTEM_BUSINESS,
    registry=REGISTRY,
)

revenue_stars_total: Counter = Counter(
    name="revenue_stars_total",
    documentation="Cumulative Telegram Stars collected from completed purchases.",
    labelnames=("package",),
    namespace=NAMESPACE,
    subsystem=SUBSYSTEM_BUSINESS,
    registry=REGISTRY,
)

revenue_usd_total: Counter = Counter(
    name="revenue_usd_total",
    documentation="Cumulative USD-denominated revenue from completed purchases.",
    labelnames=("package",),
    namespace=NAMESPACE,
    subsystem=SUBSYSTEM_BUSINESS,
    registry=REGISTRY,
)

active_users: Gauge = Gauge(
    name="active_users",
    documentation=(
        "Distinct users that issued an HTTP request in the rolling window "
        "configured via metrics_active_user_window_seconds."
    ),
    namespace=NAMESPACE,
    subsystem=SUBSYSTEM_BUSINESS,
    registry=REGISTRY,
)

payment_events_total: Counter = Counter(
    name="payment_events_total",
    documentation=(
        "Payment lifecycle events. ``event`` ∈ "
        "{invoice_created, completed, duplicate, failed, renewal}."
    ),
    labelnames=("event", "package"),
    namespace=NAMESPACE,
    subsystem=SUBSYSTEM_BUSINESS,
    registry=REGISTRY,
)

composio_timeout_without_response_total: Counter = Counter(
    name="composio_timeout_without_response_total",
    documentation=(
        "Composio tool execute calls that timed out without a response and "
        "were not retried automatically."
    ),
    labelnames=("service", "phase"),
    namespace=NAMESPACE,
    subsystem=SUBSYSTEM_PROVIDER,
    registry=REGISTRY,
)

http_requests_total: Counter = Counter(
    name="http_requests_total",
    documentation="HTTP requests completed by method, route handler and status class.",
    labelnames=("method", "handler", "status"),
    namespace=NAMESPACE,
    registry=REGISTRY,
)

http_request_duration_seconds: Histogram = Histogram(
    name="http_request_duration_seconds",
    documentation="HTTP request latency in seconds by method and route handler.",
    labelnames=("method", "handler"),
    namespace=NAMESPACE,
    registry=REGISTRY,
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)

http_requests_in_progress: Gauge = Gauge(
    name="http_requests_in_progress",
    documentation="HTTP requests currently being handled.",
    labelnames=("method", "handler"),
    namespace=NAMESPACE,
    registry=REGISTRY,
)


# ---------------------------------------------------------------- helpers

_PACKAGE_FALLBACK = "unknown"
_SERVICE_FALLBACK = "unknown"
_PHASE_FALLBACK = "unknown"


def _safe_label(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip().lower()
    return text if text else fallback


def observe_purchase(
    *,
    package: str | None,
    tokens: int,
    stars: int | None = None,
    usd: float | None = None,
) -> None:
    """Increment business counters after a payment is finalised.

    Safe to call from inside the request transaction — no I/O, no locks.
    Negative values are coerced to ``0`` so a buggy caller cannot poison
    the Prometheus counters (counters must monotonically increase).
    """
    pkg = _safe_label(package, _PACKAGE_FALLBACK)
    if tokens and tokens > 0:
        tokens_sold_total.labels(package=pkg).inc(int(tokens))
    if stars and stars > 0:
        revenue_stars_total.labels(package=pkg).inc(int(stars))
    if usd and usd > 0:
        revenue_usd_total.labels(package=pkg).inc(float(usd))


def observe_spend(*, service: str | None, tokens: int) -> None:
    if tokens and tokens > 0:
        tokens_spent_total.labels(service=_safe_label(service, _SERVICE_FALLBACK)).inc(
            int(tokens)
        )


def observe_payment_event(*, event: str, package: str | None = None) -> None:
    payment_events_total.labels(
        event=_safe_label(event, "unknown"),
        package=_safe_label(package, _PACKAGE_FALLBACK),
    ).inc()


def observe_composio_timeout_without_response(
    *,
    service: str | None,
    phase: str | None,
) -> None:
    composio_timeout_without_response_total.labels(
        service=_safe_label(service, _SERVICE_FALLBACK),
        phase=_safe_label(phase, _PHASE_FALLBACK),
    ).inc()


# ------------------------------------------------- active-users tracker


class ActiveUserTracker:
    """Sliding-window set of distinct user ids seen recently.

    Thread-safe so it can be updated from middlewares running in different
    threads (uvicorn workers share the same gauge object only inside a
    single process — that's the only contract Prometheus exporters care
    about).
    """

    def __init__(self, *, window_seconds: int, gauge: Gauge) -> None:
        self._window = max(int(window_seconds), 1)
        self._gauge = gauge
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def touch(self, user_id: str | int | None, *, now: float | None = None) -> int:
        """Record a hit for ``user_id`` and return the current active count."""
        if user_id is None or user_id == "":
            return self._gc_and_publish(now)
        key = str(user_id)
        ts = now if now is not None else time.time()
        with self._lock:
            self._seen[key] = ts
            cutoff = ts - self._window
            stale = [k for k, v in self._seen.items() if v < cutoff]
            for k in stale:
                self._seen.pop(k, None)
            count = len(self._seen)
        self._gauge.set(count)
        return count

    def _gc_and_publish(self, now: float | None) -> int:
        ts = now if now is not None else time.time()
        with self._lock:
            cutoff = ts - self._window
            stale = [k for k, v in self._seen.items() if v < cutoff]
            for k in stale:
                self._seen.pop(k, None)
            count = len(self._seen)
        self._gauge.set(count)
        return count

    def reset(self) -> None:
        with self._lock:
            self._seen.clear()
        self._gauge.set(0)


_TRACKER: ActiveUserTracker | None = None


def get_active_user_tracker(
    settings: Settings | None = None,
) -> ActiveUserTracker:
    """Return a process-wide :class:`ActiveUserTracker`, creating it once."""
    global _TRACKER
    if _TRACKER is None:
        cfg = settings or get_settings()
        _TRACKER = ActiveUserTracker(
            window_seconds=cfg.metrics_active_user_window_seconds,
            gauge=active_users,
        )
    return _TRACKER


def reset_active_user_tracker_for_tests() -> None:
    """Forget the cached tracker — tests can opt in to a fresh window."""
    global _TRACKER
    if _TRACKER is not None:
        _TRACKER.reset()
    _TRACKER = None


# --------------------------------------------------- middleware + setup


class ActiveUserMiddleware(BaseHTTPMiddleware):
    """Touch :class:`ActiveUserTracker` on every authenticated request.

    Active-user identity is read in the following order of precedence:

    1. ``request.state.user_id`` (set by JWT / Telegram auth dependencies);
    2. ``X-User-Id`` header (used by the bot webhook + Mini App);
    3. ``X-Telegram-User-Id`` header.

    Unauthenticated traffic is ignored — counting bots and uptime probes
    would inflate the gauge and ruin the SLO panels.
    """

    def __init__(self, app: Any, tracker: ActiveUserTracker) -> None:
        super().__init__(app)
        self._tracker = tracker

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        response = await call_next(request)
        with suppress(Exception):  # never break a response on metric bookkeeping
            user_id = (
                getattr(request.state, "user_id", None)
                or request.headers.get("x-user-id")
                or request.headers.get("x-telegram-user-id")
            )
            if user_id:
                self._tracker.touch(user_id)
        return response


def _route_handler(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return str(path)
    return request.url.path


def _status_group(status_code: int) -> str:
    if status_code < 100:
        return "unknown"
    return f"{status_code // 100}xx"


class HttpMetricsMiddleware(BaseHTTPMiddleware):
    """Record request count, latency and in-flight gauge for HTTP traffic."""

    def __init__(self, app: Any, excluded_paths: set[str]) -> None:
        super().__init__(app)
        self._excluded_paths = excluded_paths

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        if request.url.path in self._excluded_paths:
            return await call_next(request)

        method = request.method
        handler = request.url.path
        in_progress = http_requests_in_progress.labels(method=method, handler=handler)
        in_progress.inc()
        start = time.perf_counter()
        status = "5xx"
        try:
            response = await call_next(request)
            handler = _route_handler(request)
            status = _status_group(response.status_code)
            return response
        finally:
            duration = max(time.perf_counter() - start, 0.0)
            with suppress(Exception):
                in_progress.dec()
                http_request_duration_seconds.labels(method=method, handler=handler).observe(
                    duration
                )
                http_requests_total.labels(
                    method=method,
                    handler=handler,
                    status=status,
                ).inc()


def setup_metrics(app: FastAPI, settings: Settings | None = None) -> None:
    """Wire Prometheus instrumentation onto ``app``.

    Idempotent on the FastAPI app: a second call is a no-op so the test
    suite can build the app multiple times without 500-ing on duplicate
    ``/metrics`` routes.
    """
    cfg = settings or get_settings()
    if not cfg.metrics_enabled:
        logger.info("metrics.disabled")
        return
    if getattr(app.state, "metrics_installed", False):
        return

    excluded_paths = {cfg.metrics_path, "/health/live", "/api/v1/health/live"}

    @app.get(cfg.metrics_path, include_in_schema=False, tags=["monitoring"])
    async def metrics_endpoint() -> Response:
        return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

    tracker = get_active_user_tracker(cfg)
    app.add_middleware(HttpMetricsMiddleware, excluded_paths=excluded_paths)
    app.add_middleware(ActiveUserMiddleware, tracker=tracker)
    app.state.metrics_installed = True
    logger.info("metrics.enabled", endpoint=cfg.metrics_path)


__all__ = [
    "ActiveUserMiddleware",
    "ActiveUserTracker",
    "HttpMetricsMiddleware",
    "REGISTRY",
    "active_users",
    "composio_timeout_without_response_total",
    "get_active_user_tracker",
    "observe_composio_timeout_without_response",
    "observe_payment_event",
    "observe_purchase",
    "observe_spend",
    "payment_events_total",
    "reset_active_user_tracker_for_tests",
    "revenue_stars_total",
    "revenue_usd_total",
    "setup_metrics",
    "tokens_sold_total",
    "tokens_spent_total",
]
