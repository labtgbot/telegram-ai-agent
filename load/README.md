# Load tests

[Locust](https://locust.io/) scenario for `POST /api/v1/generate/text`.
Issue #30 ("Phase 3: Testing") sets the bar at **100 RPS** with
**p95 < 500 ms** while the **Composio mock** client is active — so the
suite exercises FastAPI routing, init-data HMAC verification, the rate
limiter, SQL transactions and the in-process generation pipeline, but
never reaches an external AI provider.

## Files

- `locustfile.py` — virtual-user definition; signs an `initData` query
  string against `BOT_TOKEN` and hammers the endpoint.
- `seed_load.py` — idempotent fixture: bumps `admin_settings.rate_limits`
  to absurd values and tops up a dedicated load user with a deep token
  balance so a 60 s run never trips `429` or `402`.
- `check_results.py` — parses Locust's CSV stats and exits non-zero if
  p95 / failure-ratio / RPS targets are violated. Used by CI.

## Local run

```bash
# 0) From the repo root, with Postgres + Redis already up
make backend-up           # or: docker compose up -d backend postgres redis

# 1) Ensure the API runs with Composio in mock mode and a known bot token.
export TELEGRAM_BOT_TOKEN=1234567890:LOAD-TEST-TOKEN
unset COMPOSIO_API_KEY    # mock client kicks in automatically

# 2) Seed quotas + load user
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_ai_agent \
  python load/seed_load.py

# 3) Drive load — 50 users, 60 seconds, no UI
mkdir -p load/out
BOT_TOKEN=$TELEGRAM_BOT_TOKEN LOAD_USER_ID=9000000001 \
  locust -f load/locustfile.py \
    --host http://127.0.0.1:8000 \
    --headless -u 50 -r 50 --run-time 60s \
    --csv=load/out/run \
    --exit-code-on-error 1

# 4) Gate the result
python load/check_results.py load/out/run_stats.csv \
  --max-p95-ms 500 --max-failure-ratio 0.0 --min-rps 80
```

Tune the workload with the standard Locust flags:

- `-u <users>` — concurrent virtual users
- `-r <rate>` — spawn rate (users/sec)
- `--run-time <duration>` — `30s`, `5m`, `1h`, …

For a stricter run, layer Locust workers (`--master` / `--worker`)
across machines.

## CI smoke

CI runs a 20-second smoke profile with 20 users (~50 RPS) to catch
regressions cheaply. The full 100-RPS run is intended for nightly /
on-demand jobs because it puts measurable load on the box.

## Environment variables

| Var                       | Default                                          | Purpose                                          |
|---------------------------|--------------------------------------------------|--------------------------------------------------|
| `BOT_TOKEN`               | _(required)_                                     | Must match the API's `TELEGRAM_BOT_TOKEN`         |
| `LOAD_USER_ID`            | `9000000001`                                     | Telegram ID minted into `initData`                |
| `LOAD_USER_FIRST_NAME`    | `Loader`                                         | First name on the synthetic Telegram identity     |
| `LOAD_USER_USERNAME`      | `loader`                                         | Username on the synthetic Telegram identity       |
| `LOAD_USER_LANGUAGE`      | `en`                                             | `language_code` field                            |
| `LOAD_USER_TOKEN_BALANCE` | `10_000_000`                                     | Tokens granted by `seed_load.py`                  |
| `LOAD_PROMPT`             | "Summarise the impact of asynchronous I/O…"     | Body of every request                            |
| `DATABASE_URL`            | `postgresql+asyncpg://postgres:postgres@…`       | Where `seed_load.py` writes                       |
