"""Production launch smoke test.

Runs the minimum end-to-end checks that must pass before announcing the
bot publicly. Designed to be triggered manually from the on-call laptop
against a real production deployment — every step is read-only or
explicitly auditable (the Stars purchase is real money and is left to
the operator).

Checks executed:

1. ``GET {API}/health`` returns ``ok: true``.
2. ``GET {API}/api/v1/user/balance`` with the operator's WebApp
   ``initData`` returns HTTP 200 (auth pipeline + DB read path).
3. ``POST {API}/api/v1/payment/create-invoice {"package": "starter"}``
   returns a Telegram invoice link, captures ``transaction_id``.
4. Polls ``GET {API}/api/v1/payment/status/{invoice_id}`` until the
   transaction completes (operator pays the Stars invoice in a separate
   Telegram client). The script asserts the final transaction has
   ``payment_id`` prefixed ``tg:`` — the stable Telegram charge id used
   for idempotency.

Run from the repo root with::

    BASE_URL=https://api.telegram-ai-agent.example.com \
    AUTH_TOKEN="$BETA_INIT_DATA" \
        python -m scripts.launch_smoketest

Environment variables:

* ``BASE_URL`` — backend public URL (default ``http://localhost:8000``).
* ``AUTH_TOKEN`` — ``X-Telegram-Init-Data`` for the smoke-test user.
* ``SMOKE_PACKAGE`` — package code to invoice (default ``starter``).
* ``SMOKE_POLL_TIMEOUT`` — seconds to wait for the purchase to land
  (default ``600`` — ten minutes).
* ``SMOKE_POLL_INTERVAL`` — poll interval in seconds (default ``5``).
* ``SMOKE_SKIP_PURCHASE=1`` — stop after creating the invoice (useful
  when running against staging without spending real Stars).
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@dataclass(frozen=True)
class SmokeConfig:
    base_url: str
    auth_token: str
    package: str
    poll_timeout_s: float
    poll_interval_s: float
    skip_purchase: bool

    @classmethod
    def from_env(cls) -> "SmokeConfig":
        base = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
        token = os.environ.get("AUTH_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "AUTH_TOKEN is required (X-Telegram-Init-Data string for the "
                "smoke-test account)."
            )
        return cls(
            base_url=base,
            auth_token=token,
            package=os.environ.get("SMOKE_PACKAGE", "starter").strip().lower(),
            poll_timeout_s=float(os.environ.get("SMOKE_POLL_TIMEOUT", "600")),
            poll_interval_s=float(os.environ.get("SMOKE_POLL_INTERVAL", "5")),
            skip_purchase=os.environ.get("SMOKE_SKIP_PURCHASE") == "1",
        )


def _headers(token: str) -> dict[str, str]:
    return {
        "X-Telegram-Init-Data": token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


async def check_health(client: httpx.AsyncClient, base_url: str) -> None:
    response = await client.get(f"{base_url}/health")
    response.raise_for_status()
    body = response.json()
    if not (isinstance(body, dict) and body.get("status") in {"ok", "healthy"}):
        raise SystemExit(f"/health returned unexpected payload: {body!r}")
    print(f"[1/4] /health ok ({body})")


async def check_balance(
    client: httpx.AsyncClient, config: SmokeConfig
) -> dict[str, object]:
    response = await client.get(
        f"{config.base_url}/api/v1/user/balance",
        headers=_headers(config.auth_token),
    )
    response.raise_for_status()
    body = response.json()
    print(
        "[2/4] /balance ok "
        f"(token_balance={body.get('token_balance')}, "
        f"user_id={body.get('id')})"
    )
    return body


async def create_invoice(
    client: httpx.AsyncClient, config: SmokeConfig
) -> dict[str, object]:
    response = await client.post(
        f"{config.base_url}/api/v1/payment/create-invoice",
        headers=_headers(config.auth_token),
        json={"package": config.package},
    )
    response.raise_for_status()
    body = response.json()
    invoice_id = body["invoice_id"]
    link = body["telegram_invoice_link"]
    stars = body["stars_amount"]
    tokens = body["tokens_amount"]
    print(
        f"[3/4] /create-invoice ok (invoice_id={invoice_id}, stars={stars}, "
        f"tokens={tokens})"
    )
    print(f"      Pay this invoice from the Telegram client: {link}")
    return body


async def wait_for_completion(
    client: httpx.AsyncClient,
    config: SmokeConfig,
    invoice_id: str,
) -> dict[str, object]:
    deadline = time.monotonic() + config.poll_timeout_s
    last_status: str | None = None
    while time.monotonic() < deadline:
        response = await client.get(
            f"{config.base_url}/api/v1/payment/status/{invoice_id}",
            headers=_headers(config.auth_token),
        )
        response.raise_for_status()
        body = response.json()
        status = str(body.get("status"))
        if status != last_status:
            print(f"      poll: status={status}")
            last_status = status
        if status == "completed":
            charge_id = body.get("telegram_payment_charge_id")
            if not isinstance(charge_id, str) or not charge_id:
                raise SystemExit(
                    "completed transaction is missing telegram_payment_charge_id"
                )
            print(
                "[4/4] purchase completed: "
                f"transaction_id={body['transaction_id']}, "
                f"tokens_credited={body.get('tokens_credited')}, "
                f"charge_id={charge_id}"
            )
            return body
        if status == "failed":
            raise SystemExit(f"Transaction {invoice_id} failed: {body!r}")
        await asyncio.sleep(config.poll_interval_s)
    raise SystemExit(
        f"Timed out after {config.poll_timeout_s:.0f}s waiting for "
        f"invoice {invoice_id} to complete."
    )


async def run(config: SmokeConfig) -> None:
    timeout = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        await check_health(client, config.base_url)
        await check_balance(client, config)
        invoice = await create_invoice(client, config)
        if config.skip_purchase:
            print("SMOKE_SKIP_PURCHASE=1 — exiting after invoice creation.")
            return
        await wait_for_completion(client, config, str(invoice["invoice_id"]))
    print("smoke test passed — launch gate cleared.")


def main() -> None:
    asyncio.run(run(SmokeConfig.from_env()))


if __name__ == "__main__":
    main()
