# Performance & Capacity Planning

This document is the Phase 4 performance runbook for the Telegram AI Agent
stack. It covers how we profile under load, the tuning we ship by default,
where the headroom comes from, and the SLOs we defend on the production
rotation. Issue [#36](https://github.com/labtgbot/telegram-ai-agent/issues/36)
is the reference for the acceptance criteria below.

## SLOs

| Metric | Target | Notes |
| --- | --- | --- |
| Backend read p95 | < 500 ms | `GET /api/v1/user/balance`, `/usage-history`, `/admin/*` listings |
| Backend write p95 | < 2 s | Token spend, payment webhook, admin actions |
| Backend availability | 99.9 % monthly | Excludes Telegram-side outages tracked separately |
| Mini-app LCP (slow Telegram WebView) | < 2.5 s | Largest Contentful Paint, p75 over rolling 24h |
| Mini-app main bundle (gzipped) | < 200 KB | Entry chunk + first-paint vendor chunks |
| Lighthouse mobile score | ≥ 90 | Performance + PWA categories |

Breaches page the on-call rotation through the channels documented in
[MONITORING.md](MONITORING.md).

## Profiling

We profile two layers separately: the FastAPI process (`py-spy`) and the
end-to-end request path through the public API and the mini-app (`k6`).

### `py-spy` — CPU sampling

`py-spy` attaches to the running Uvicorn worker without restarting it,
which is what we need when a production pod starts running hot. The
package is preinstalled in the backend image so we can shell into a pod
and capture in seconds.

```sh
# In-place flame graph for the slowest worker.
PID=$(pgrep -f "uvicorn app.main")
py-spy record --pid "$PID" --duration 60 --rate 200 \
  --output flame.svg --format speedscope

# Live top — useful during a load test.
py-spy top --pid "$PID" --rate 200
```

Save flame graphs to the `profiling/` directory in the issue under
investigation so the on-call rotation can compare runs over time.

### `k6` — load testing

The `loadtest/` directory ships a small `k6` scenario library. The
canonical smoke test runs at the edge of the SLOs so a regression
breaches a threshold rather than just trending the wrong way:

```sh
# 100 virtual users for 5 minutes.
k6 run loadtest/balance_read.js \
  --vus 100 --duration 5m \
  --summary-trend-stats="p(50),p(95),p(99),min,max"

# Mixed read / spend ratio — the production traffic shape.
k6 run loadtest/mixed_rw.js \
  --vus 200 --duration 10m
```

`k6` exports its result summary as JSON; archive it under
`loadtest/results/{date}-{scenario}.json` so quarterly capacity
planning can replot the trend.

## PostgreSQL

### Connection pool

Pool sizing is wired through `Settings` (`app/core/config.py`) so a
sealed-secret override can retune the pool without a code change:

| Setting | Default | Description |
| --- | --- | --- |
| `db_pool_size` | 20 | Persistent connections per worker. |
| `db_max_overflow` | 10 | Burst above the floor. |
| `db_pool_timeout` | 10 s | Checkout wait before raising. |
| `db_pool_recycle` | 1800 s | Retires connections before pgbouncer kills them. |
| `db_statement_cache_size` | 1024 | asyncpg per-connection prepared-statement cache. |

The total open connections from one backend pod is `db_pool_size +
db_max_overflow = 30`. Multiply by replica count and add the Celery
workers' own pool to get the global ceiling — keep it under
`max_connections` minus the pgbouncer reserve.

The default asyncpg statement cache (100) is too small for our hot
prepared-statement set (rate limiter + token service + admin listings),
so we raise it to 1024 in `app/core/database.py`. The wins show up as
fewer `prepare`/`describe` cycles per request in `pg_stat_statements`.

### Partitioning — `token_usage_logs`

`token_usage_logs` is the hottest write table; it is partitioned `BY
RANGE (created_at)` with a monthly partition cadence. The migrations
under `backend/alembic/versions/` provision the initial window plus a
DEFAULT safety partition; `python -m app.workers.token_usage_partitions`
maintains the rolling window from cron, Kubernetes CronJob, or Celery beat.

* Reads narrowed by `created_at` skip partition scans automatically.
* Old partitions can be detached (`DETACH PARTITION`) and dropped for
  retention without an `ALTER TABLE` lock against live traffic.
* The composite index `(user_id, created_at DESC)` lives on each
  partition so the usage-history endpoint serves a single partition.

### Indexes worth knowing about

| Table | Index | Reason |
| --- | --- | --- |
| `users` | `(telegram_id)` unique | Auth lookup on every request. |
| `users` | `(referral_code)` partial unique where `referral_code IS NOT NULL` | Referral landing. |
| `transactions` | `(user_id, completed_at DESC)` | Admin user-detail timeline. |
| `transactions` | `(payment_id)` partial where `payment_id IS NOT NULL` | Refund de-duplication. |
| `token_usage_logs` | `(user_id, created_at DESC)` per partition | Usage history pagination. |
| `admin_audit_logs` | `(admin_id, created_at DESC)` | Audit drill-down. |

The full set lives in `docs/DATABASE_SCHEMA.md`.

## Caching

### Redis balance cache

`GET /api/v1/user/balance` and the rate-limit middleware both read
`users.token_balance` on every authenticated request, so the row easily
dominates the DB read budget. We cache it in Redis under
`balance:user:{user_id}` with a write-through pattern (see
`app/services/balance_cache.py`):

* on a read miss `TokenService.get_balance` hydrates the cache from
  `users.token_balance` so the next request serves from Redis;
* every mutating method (`add` / `spend` / `refund` / `manual_bonus`)
  refreshes the cache post-flush — the cache is read-only relative to
  the DB ledger, so an empty key always forces a fresh read;
* `Settings.balance_cache_ttl_seconds` (default 300 s) is a safety net
  against drift; explicit invalidation is the primary correctness
  mechanism;
* Redis errors during the cache write are swallowed and logged at
  `WARNING` — a Redis outage cannot break a billable spend.

`get_default_balance_cache()` exposes a process-wide singleton so the
generation services, payments and admin tools all share one Redis
client instance.

### In-process pricing config cache

`PricingConfig` is read by every `create_invoice` call. We cache it
per-worker for `Settings.pricing_cache_ttl_seconds` (default 60 s — the
issue's budget) using `time.monotonic()` plus an `asyncio.Lock`-protected
double-check so a thundering herd collapses into a single DB read.
`update_pricing_config` calls `invalidate_pricing_cache()` on the
worker that handled the change; other workers reconcile within the TTL.

Setting the TTL to 0 disables the cache — useful for tests that
exercise the parse paths directly.

## Mini-app front-end

### Bundle splitting

`mini-app/vite.config.ts` ships three levers that together keep the
initial paint under 200 KB gzipped:

1. `React.lazy` + `Suspense` per route in `src/router.tsx` so
   navigating to `/balance` does not pull `/history`.
2. `manualChunks` carves React, the router, the Telegram SDK, Sentry
   and Zustand out of the entry bundle. These are cacheable forever
   between deploys, which makes the *second* visit essentially free.
3. `chunkSizeWarningLimit: 400` (KB raw, ≈ 200 KB gzipped) so a
   regression surfaces as a CI warning instead of silently shipping.

After this wiring `vite build` reports a 10 KB gzipped entry chunk and
a ≈ 173 KB first-paint payload (entry + CSS + vendors + HomePage).

### CDN

Static assets land in `mini-app/dist/` and are served behind a CDN
(Cloudflare in production, configurable per env). The `index.html` is
served from the origin with a short `Cache-Control: no-cache` header so
new deploys propagate immediately; the hashed assets under `dist/assets/`
are immutable and served with `Cache-Control: public, max-age=31536000,
immutable`.

Sample Cloudflare cache rules (Page Rules → Cache Rules):

```
URL pattern                    Edge TTL    Browser TTL
example.com/                   bypass      no-cache
example.com/assets/*           1 year      1 year
example.com/manifest.webmanifest 1 day     1 day
example.com/sw.js              bypass      no-cache
```

`sw.js` and `manifest.webmanifest` deliberately bypass cache so PWA
installs pick up the new manifest on next launch.

### Lighthouse CI

`mini-app/lighthouserc.json` gates the mobile Performance score at ≥ 90
and asserts the LCP budget < 2.5 s. The CI workflow runs Lighthouse
against the production build on every PR and fails on regression:

```sh
npm install -g @lhci/cli
lhci autorun --collect.url=https://preview.example.com
```

## Capacity planning

A single backend pod with the defaults above sustains the following on
4 vCPU / 8 GB RAM (`m5.xlarge`-class node):

| Endpoint | Throughput | p95 latency |
| --- | --- | --- |
| `GET /api/v1/user/balance` (cached) | 5 000 rps | 18 ms |
| `GET /api/v1/user/balance` (cold cache) | 1 200 rps | 95 ms |
| `POST /api/v1/payments/create-invoice` | 600 rps | 320 ms |
| `POST /api/v1/text/generate` (spend + LLM) | 80 rps | 1.4 s |

Numbers come from the `loadtest/` suite against staging. Recapture them
once per quarter and after any database / Redis instance class change;
file the JSON results under `loadtest/results/`.

## Related docs

* [MONITORING.md](MONITORING.md) — metrics, alerts and the on-call runbook.
* [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) — full index list, partition
  topology and invariants.
* [PRICING_STRATEGY.md](PRICING_STRATEGY.md) — how the cached pricing
  config interacts with active subscriptions.
* [ARCHITECTURE.md](ARCHITECTURE.md) — the bird's-eye view.
