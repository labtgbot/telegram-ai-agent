"""Locust load test for ``POST /api/v1/generate/text``.

This scenario targets the text-generation endpoint with the Composio
**mock** client active (`COMPOSIO_API_KEY` unset on the server), so it
exercises the FastAPI routing, auth, rate-limiting, SQL transactions and
the in-process generation pipeline — but never reaches an external AI
provider.

Acceptance target (issue #30, Phase 3 "Load"):

* sustained **100 RPS** on ``POST /api/v1/generate/text``
* **p95 < 500 ms**

Usage::

    # 1) Boot the API with the load profile (see load/README.md).
    # 2) Bump rate limits and seed a load user with a large balance:
    DATABASE_URL=... python load/seed_load.py
    # 3) Drive load:
    BOT_TOKEN=<token> LOAD_USER_ID=9000000001 \
        locust -f load/locustfile.py \
            --host http://127.0.0.1:8000 \
            --headless -u 50 -r 50 --run-time 60s \
            --csv=load/out/run \
            --exit-code-on-error 1

The companion script ``load/check_results.py`` parses
``load/out/run_stats.csv`` and exits non-zero if p95 is above the
threshold or failure ratio is non-zero — wire it into CI to gate
regressions.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import random
import time
from typing import Any
from urllib.parse import urlencode

from locust import HttpUser, between, events, task


BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
USER_ID = int(os.environ.get("LOAD_USER_ID", "9000000001"))
USER_FIRST_NAME = os.environ.get("LOAD_USER_FIRST_NAME", "Loader")
USER_USERNAME = os.environ.get("LOAD_USER_USERNAME", "loader")
USER_LANGUAGE = os.environ.get("LOAD_USER_LANGUAGE", "en")
TEXT_PROMPT = os.environ.get(
    "LOAD_PROMPT",
    "Summarise the impact of asynchronous I/O on web-service throughput.",
)


@events.test_start.add_listener
def _on_test_start(environment, **_: Any) -> None:  # pragma: no cover - locust lifecycle hook
    """Fail fast if the operator forgot to wire the bot token in."""
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN env var must be set (must match the API's "
            "TELEGRAM_BOT_TOKEN). Without it the HMAC on initData will "
            "not validate and every request will return 401."
        )


def _sign_init_data(
    *,
    bot_token: str,
    telegram_id: int,
    first_name: str,
    username: str,
    language_code: str,
    auth_date: int | None = None,
    query_id: str = "AAEvAAAAAA",
) -> str:
    """Build a Telegram WebApp ``initData`` query string signed for ``bot_token``.

    Mirrors the procedure documented at
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    and the verification code in :mod:`app.auth.telegram` — keep the two
    in sync if Telegram changes the algorithm.
    """
    user_payload = json.dumps(
        {
            "id": telegram_id,
            "first_name": first_name,
            "username": username,
            "language_code": language_code,
        },
        separators=(",", ":"),
    )
    pairs: list[tuple[str, str]] = [
        ("query_id", query_id),
        ("user", user_payload),
        ("auth_date", str(auth_date if auth_date is not None else int(time.time()))),
    ]
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs, key=lambda kv: kv[0]))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    pairs.append(("hash", digest))
    return urlencode(pairs)


class TextGenerationUser(HttpUser):
    """Drive ``POST /api/v1/generate/text`` at a high request rate."""

    # ``between(0, 0.01)`` keeps the loop tight so a modest number of workers
    # can sustain ~100 RPS on a single host. Tune via Locust's ``-u`` if you
    # want to push higher.
    wait_time = between(0.0, 0.01)

    def on_start(self) -> None:
        """Mint the initData header once per virtual user."""
        # Stagger ``auth_date`` slightly so identical headers don't collide in
        # any caching layer that might key on the raw initData string.
        auth_date = int(time.time()) - random.randint(0, 30)
        self._init_data = _sign_init_data(
            bot_token=BOT_TOKEN,
            telegram_id=USER_ID,
            first_name=USER_FIRST_NAME,
            username=USER_USERNAME,
            language_code=USER_LANGUAGE,
            auth_date=auth_date,
        )
        self.client.headers.update(
            {
                "X-Telegram-Init-Data": self._init_data,
                "Content-Type": "application/json",
            }
        )

    @task
    def generate_text(self) -> None:
        body = {
            "prompt": TEXT_PROMPT,
            "mode": "basic",  # cheapest mode (1 token) — bound by load_seed balance
            "max_tokens": 64,
            "temperature": 0.2,
        }
        with self.client.post(
            "/api/v1/generate/text",
            json=body,
            name="POST /generate/text",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                response.success()
            elif response.status_code == 402:
                response.failure(
                    "insufficient_tokens — top up the load user "
                    "(see load/seed_load.py)"
                )
            elif response.status_code == 429:
                response.failure(
                    "rate_limited — bump admin_settings.rate_limits "
                    "(see load/seed_load.py)"
                )
            else:
                response.failure(
                    f"unexpected status {response.status_code}: "
                    f"{response.text[:200]}"
                )
