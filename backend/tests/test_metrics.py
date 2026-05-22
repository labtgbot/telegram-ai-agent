"""Tests for ``app.core.metrics``.

Covers the helpers that touch business counters, the sliding-window active
user tracker, and the ``/metrics`` endpoint wiring through ``setup_metrics``.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from prometheus_client import CollectorRegistry, Gauge

from app.core import metrics as metrics_module
from app.core.metrics import (
    REGISTRY,
    ActiveUserTracker,
    active_users,
    get_active_user_tracker,
    observe_payment_event,
    observe_purchase,
    observe_spend,
    payment_events_total,
    reset_active_user_tracker_for_tests,
    revenue_stars_total,
    revenue_usd_total,
    tokens_sold_total,
    tokens_spent_total,
)


@pytest.fixture(autouse=True)
def reset_business_metrics() -> None:
    """Each test starts with zeroed business counters."""
    tokens_sold_total._metrics.clear()
    tokens_spent_total._metrics.clear()
    revenue_stars_total._metrics.clear()
    revenue_usd_total._metrics.clear()
    payment_events_total._metrics.clear()
    active_users.set(0)
    reset_active_user_tracker_for_tests()
    yield
    reset_active_user_tracker_for_tests()


def _counter_value(counter: Any, **labels: str) -> float:
    return counter.labels(**labels)._value.get()  # type: ignore[no-any-return]


def test_observe_purchase_increments_all_counters() -> None:
    observe_purchase(package="starter", tokens=100, stars=50, usd=0.99)
    assert _counter_value(tokens_sold_total, package="starter") == 100
    assert _counter_value(revenue_stars_total, package="starter") == 50
    assert _counter_value(revenue_usd_total, package="starter") == pytest.approx(0.99)


def test_observe_purchase_ignores_zero_and_negative_values() -> None:
    observe_purchase(package="free", tokens=0, stars=-1, usd=-0.5)
    # No samples should have been created at all.
    assert ("free",) not in tokens_sold_total._metrics
    assert ("free",) not in revenue_stars_total._metrics
    assert ("free",) not in revenue_usd_total._metrics


def test_observe_purchase_falls_back_to_unknown_label_when_package_missing() -> None:
    observe_purchase(package=None, tokens=10)
    assert _counter_value(tokens_sold_total, package="unknown") == 10


def test_observe_spend_counts_by_service() -> None:
    observe_spend(service="image_generation", tokens=5)
    observe_spend(service="image_generation", tokens=3)
    observe_spend(service="text_generation", tokens=1)
    assert _counter_value(tokens_spent_total, service="image_generation") == 8
    assert _counter_value(tokens_spent_total, service="text_generation") == 1


def test_observe_payment_event_records_each_event_type() -> None:
    observe_payment_event(event="invoice_created", package="starter")
    observe_payment_event(event="completed", package="starter")
    observe_payment_event(event="duplicate", package="starter")
    observe_payment_event(event="renewal", package="pro")

    assert _counter_value(payment_events_total, event="invoice_created", package="starter") == 1
    assert _counter_value(payment_events_total, event="completed", package="starter") == 1
    assert _counter_value(payment_events_total, event="duplicate", package="starter") == 1
    assert _counter_value(payment_events_total, event="renewal", package="pro") == 1


# ----------------------------------------------------- ActiveUserTracker


def test_active_user_tracker_counts_distinct_users_in_window() -> None:
    gauge = Gauge("test_active_users", "test", registry=CollectorRegistry())
    tracker = ActiveUserTracker(window_seconds=60, gauge=gauge)
    now = 1_000.0
    tracker.touch(1, now=now)
    tracker.touch(2, now=now + 1)
    tracker.touch(1, now=now + 2)  # duplicate hit for user 1
    assert tracker.touch(3, now=now + 3) == 3


def test_active_user_tracker_expires_stale_entries() -> None:
    gauge = Gauge("test_active_users_expiry", "test", registry=CollectorRegistry())
    tracker = ActiveUserTracker(window_seconds=10, gauge=gauge)
    tracker.touch("u1", now=0)
    tracker.touch("u2", now=5)
    # advance past the window for u1 only
    count = tracker.touch("u3", now=12)
    assert count == 2  # u1 expired, u2 + u3 remain


def test_active_user_tracker_touch_returns_count_for_missing_user() -> None:
    gauge = Gauge("test_active_users_none", "test", registry=CollectorRegistry())
    tracker = ActiveUserTracker(window_seconds=60, gauge=gauge)
    tracker.touch("known", now=0)
    assert tracker.touch(None, now=1) == 1
    assert tracker.touch("", now=1) == 1


def test_active_user_tracker_reset_clears_state() -> None:
    gauge = Gauge("test_active_users_reset", "test", registry=CollectorRegistry())
    tracker = ActiveUserTracker(window_seconds=60, gauge=gauge)
    tracker.touch("u1", now=0)
    tracker.reset()
    assert tracker.touch(None, now=1) == 0


def test_get_active_user_tracker_returns_singleton() -> None:
    first = get_active_user_tracker()
    second = get_active_user_tracker()
    assert first is second


# ----------------------------------------------------- /metrics endpoint


@pytest.fixture
def fake_engine() -> MagicMock:
    engine = MagicMock()
    conn = AsyncMock()
    conn.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 1))

    @asynccontextmanager
    async def _connect(*args: Any, **kwargs: Any):
        yield conn

    engine.connect = _connect
    engine.dispose = AsyncMock()
    return engine


@pytest.fixture
def fake_redis_ok() -> MagicMock:
    redis = MagicMock()
    redis.ping = AsyncMock(return_value=True)
    redis.aclose = AsyncMock()
    return redis


async def test_metrics_endpoint_serves_prometheus_text(
    fake_engine: MagicMock, fake_redis_ok: MagicMock
) -> None:
    """The exporter responds on the configured metrics path."""
    with (
        patch("app.api.v1.health.get_engine", return_value=fake_engine),
        patch("app.api.v1.health.get_redis", return_value=fake_redis_ok),
        patch("app.main.get_engine", return_value=fake_engine),
    ):
        from app.main import app

        async with LifespanManager(app), AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/metrics")

        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        body = resp.text
        # The instrumentator standard series should be present.
        assert "# HELP" in body
        # Triggering an HTTP call should produce request counters.
        assert "http_requests_total" in body or "http_request_duration_seconds" in body


def test_metrics_module_uses_dedicated_registry_not_global() -> None:
    """Business counters are isolated so tests can reset them freely."""
    assert REGISTRY is not None
    assert isinstance(REGISTRY, CollectorRegistry)
    # The default registry should not see our tgai_business_* series.
    from prometheus_client import REGISTRY as DEFAULT_REGISTRY

    names = {m.name for m in DEFAULT_REGISTRY.collect()}
    assert "tgai_business_tokens_sold" not in names


def test_setup_metrics_is_idempotent(fake_engine: MagicMock, fake_redis_ok: MagicMock) -> None:
    """A second ``setup_metrics`` call must not crash on duplicate routes."""
    with (
        patch("app.api.v1.health.get_engine", return_value=fake_engine),
        patch("app.api.v1.health.get_redis", return_value=fake_redis_ok),
        patch("app.main.get_engine", return_value=fake_engine),
    ):
        from app.main import app

        # ``create_app`` already called setup_metrics once during import.
        assert getattr(app.state, "metrics_installed", False) is True
        metrics_module.setup_metrics(app)  # second call — should no-op
        assert app.state.metrics_installed is True
