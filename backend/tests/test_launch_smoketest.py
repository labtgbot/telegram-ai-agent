"""Tests for ``scripts/launch_smoketest.py``.

We mount an ``httpx.MockTransport`` so the smoke-test runner exercises
the real backend contract (paths, headers, polling) without a live API.
"""
from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import launch_smoketest  # noqa: E402
from scripts.launch_smoketest import SmokeConfig, run  # noqa: E402


_RealAsyncClient = httpx.AsyncClient


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.AsyncClient:
    return _RealAsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_run_skip_purchase_stops_after_invoice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        seen.append(f"{request.method} {path}")
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/v1/user/balance":
            return httpx.Response(
                200,
                json={"id": 1, "telegram_id": 42, "token_balance": 100},
            )
        if path == "/api/v1/payment/create-invoice":
            return httpx.Response(
                200,
                json={
                    "invoice_id": "starter:1:abc",
                    "stars_amount": 250,
                    "tokens_amount": 500,
                    "telegram_invoice_link": "https://t.me/invoice/x",
                    "transaction_id": 99,
                    "is_subscription": False,
                },
            )
        raise AssertionError(f"unexpected request: {path}")

    monkeypatch.setattr(
        launch_smoketest.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _client(handler),
    )

    config = SmokeConfig(
        base_url="http://test.invalid",
        auth_token="initdata",
        package="starter",
        poll_timeout_s=1.0,
        poll_interval_s=0.1,
        skip_purchase=True,
    )
    await run(config)

    assert seen == [
        "GET /health",
        "GET /api/v1/user/balance",
        "POST /api/v1/payment/create-invoice",
    ]


@pytest.mark.asyncio
async def test_run_polls_until_completed(monkeypatch: pytest.MonkeyPatch) -> None:
    poll_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/v1/user/balance":
            return httpx.Response(
                200, json={"id": 1, "telegram_id": 42, "token_balance": 0}
            )
        if path == "/api/v1/payment/create-invoice":
            return httpx.Response(
                200,
                json={
                    "invoice_id": "starter:1:abc",
                    "stars_amount": 250,
                    "tokens_amount": 500,
                    "telegram_invoice_link": "https://t.me/invoice/x",
                    "transaction_id": 99,
                    "is_subscription": False,
                },
            )
        if path.startswith("/api/v1/payment/status/"):
            poll_count["n"] += 1
            if poll_count["n"] < 2:
                return httpx.Response(
                    200,
                    json={
                        "invoice_id": "starter:1:abc",
                        "status": "pending",
                        "package": "starter",
                        "tokens_credited": 0,
                        "stars_amount": 250,
                        "transaction_id": 99,
                        "created_at": "2026-05-16T00:00:00Z",
                        "completed_at": None,
                        "telegram_payment_charge_id": None,
                    },
                )
            return httpx.Response(
                200,
                json={
                    "invoice_id": "starter:1:abc",
                    "status": "completed",
                    "package": "starter",
                    "tokens_credited": 500,
                    "stars_amount": 250,
                    "transaction_id": 99,
                    "created_at": "2026-05-16T00:00:00Z",
                    "completed_at": "2026-05-16T00:00:05Z",
                    "telegram_payment_charge_id": "abc123",
                },
            )
        raise AssertionError(f"unexpected request: {path}")

    monkeypatch.setattr(
        launch_smoketest.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _client(handler),
    )

    config = SmokeConfig(
        base_url="http://test.invalid",
        auth_token="initdata",
        package="starter",
        poll_timeout_s=5.0,
        poll_interval_s=0.05,
        skip_purchase=False,
    )
    await run(config)
    assert poll_count["n"] == 2


@pytest.mark.asyncio
async def test_run_fails_when_transaction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if path == "/api/v1/user/balance":
            return httpx.Response(
                200, json={"id": 1, "telegram_id": 42, "token_balance": 0}
            )
        if path == "/api/v1/payment/create-invoice":
            return httpx.Response(
                200,
                json={
                    "invoice_id": "starter:1:abc",
                    "stars_amount": 250,
                    "tokens_amount": 500,
                    "telegram_invoice_link": "https://t.me/invoice/x",
                    "transaction_id": 99,
                    "is_subscription": False,
                },
            )
        if path.startswith("/api/v1/payment/status/"):
            return httpx.Response(
                200,
                json={
                    "invoice_id": "starter:1:abc",
                    "status": "failed",
                    "package": "starter",
                    "tokens_credited": 0,
                    "stars_amount": 250,
                    "transaction_id": 99,
                    "created_at": "2026-05-16T00:00:00Z",
                    "completed_at": None,
                    "telegram_payment_charge_id": None,
                },
            )
        raise AssertionError(f"unexpected request: {path}")

    monkeypatch.setattr(
        launch_smoketest.httpx,
        "AsyncClient",
        lambda *args, **kwargs: _client(handler),
    )

    config = SmokeConfig(
        base_url="http://test.invalid",
        auth_token="initdata",
        package="starter",
        poll_timeout_s=1.0,
        poll_interval_s=0.05,
        skip_purchase=False,
    )
    with pytest.raises(SystemExit, match="failed"):
        await run(config)


def test_from_env_requires_auth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AUTH_TOKEN", raising=False)
    monkeypatch.delenv("BASE_URL", raising=False)
    with pytest.raises(SystemExit, match="AUTH_TOKEN"):
        SmokeConfig.from_env()


def test_from_env_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTH_TOKEN", "abc")
    monkeypatch.delenv("BASE_URL", raising=False)
    monkeypatch.delenv("SMOKE_PACKAGE", raising=False)
    monkeypatch.delenv("SMOKE_POLL_TIMEOUT", raising=False)
    monkeypatch.delenv("SMOKE_POLL_INTERVAL", raising=False)
    monkeypatch.delenv("SMOKE_SKIP_PURCHASE", raising=False)
    config = SmokeConfig.from_env()
    assert config.base_url == "http://localhost:8000"
    assert config.package == "starter"
    assert config.poll_timeout_s == 600.0
    assert config.poll_interval_s == 5.0
    assert config.skip_purchase is False
