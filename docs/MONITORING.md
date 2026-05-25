# Monitoring, Logging & Alerting

This document is the runbook for Phase 4 monitoring of the Telegram AI Agent
backend, mini-app and admin dashboard. It covers metrics, logs, errors,
alerts and the SLI/SLO contract the on-call rotation defends.

## Stack overview

```
┌────────────┐   /metrics   ┌─────────────┐   alerts    ┌──────────────┐
│  Backend   ├─────────────►│ Prometheus  ├────────────►│ Alertmanager │
│ (FastAPI)  │              │             │             │              │
└─────┬──────┘              └──────┬──────┘             └──────┬───────┘
      │ stdout JSON                │                            │ Telegram
      ▼                            ▼                            ▼
┌────────────┐              ┌─────────────┐             ┌──────────────┐
│  Promtail  ├─────────────►│    Loki     │             │  On-call     │
└────────────┘              └──────┬──────┘             │  chat        │
                                   │                    └──────────────┘
                                   ▼
                            ┌─────────────┐
                            │   Grafana   │
                            └─────────────┘
```

* **Metrics** – `app.core.metrics` exposes HTTP metrics on `/metrics` and
  registers business KPIs
  (`tokens_sold_total`, `tokens_spent_total`, `revenue_stars_total`,
  `revenue_usd_total`, `active_users`, `payment_events_total`).
* **Logs** – structured JSON logs emitted by `structlog` (configure with
  `LOG_FORMAT=json`). Promtail collects them and ships them to Loki.
* **Errors** – Sentry SDKs in the backend (`sentry-sdk[fastapi]`), mini-app
  (`@sentry/react`) and admin dashboard (`@sentry/nextjs`). DSN-gated so
  local development never ships events.
* **Alerts** – Prometheus rules under `deploy/monitoring/prometheus/rules`
  fire into Alertmanager, which delivers messages to the on-call Telegram
  chat (`telegram_configs` receiver).
* **Dashboards** – three Grafana dashboards under
  `deploy/monitoring/grafana/dashboards`: `business.json`, `infra.json`,
  `slo.json`.

## Running the stack locally

```bash
docker compose -f deploy/monitoring/docker-compose.monitoring.yml up -d
# Grafana    → http://localhost:3000  (admin / admin)
# Prometheus → http://localhost:9090
# Alertmgr   → http://localhost:9093
# Loki       → http://localhost:3100
```

Start the backend with `METRICS_ENABLED=true` (default) and, optionally,
`SENTRY_DSN=…` to verify error reporting.

## Configuration reference

### Backend env vars

| Variable | Default | Notes |
| --- | --- | --- |
| `METRICS_ENABLED` | `true` | Mount `/metrics` and install the active-users middleware. |
| `METRICS_PATH` | `/metrics` | Where the exporter listens. |
| `METRICS_ACTIVE_USER_WINDOW_SECONDS` | `300` | Sliding-window length for `active_users`. |
| `SENTRY_DSN` | `""` | Empty disables Sentry. |
| `SENTRY_ENVIRONMENT` | `app_env` | Falls back to `APP_ENV`. |
| `SENTRY_RELEASE` | derived | Defaults to `telegram-ai-agent-backend@<version>`. |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Server-side tracing sample rate. |
| `SENTRY_PROFILES_SAMPLE_RATE` | `0.0` | Optional profiling sample rate. |
| `LOG_FORMAT` | `console` | Set to `json` in production for Loki/ELK ingestion. |
| `LOG_LEVEL` | `INFO` | Standard log level. |

### Mini-app env vars (Vite)

| Variable | Default |
| --- | --- |
| `VITE_SENTRY_DSN` | empty (disabled) |
| `VITE_SENTRY_ENVIRONMENT` | `MODE` |
| `VITE_SENTRY_TRACES_SAMPLE_RATE` | `0.1` |
| `VITE_SENTRY_REPLAYS_SESSION_SAMPLE_RATE` | `0` |
| `VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE` | `0` |

### Admin dashboard env vars (Next.js)

| Variable | Default |
| --- | --- |
| `NEXT_PUBLIC_SENTRY_DSN` | empty (disabled) |
| `SENTRY_DSN` | falls back to `NEXT_PUBLIC_SENTRY_DSN` |
| `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | `0.1` |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` |

## Custom metrics

All custom series are namespaced under `tgai_business_*` (Prometheus
namespace `tgai`, subsystem `business`):

| Series | Type | Labels | When emitted |
| --- | --- | --- | --- |
| `tgai_business_tokens_sold_total` | counter | `package` | Successful purchase / renewal credits tokens. |
| `tgai_business_tokens_spent_total` | counter | `service` | `TokenService.spend()` debits tokens. |
| `tgai_business_revenue_stars_total` | counter | `package` | Telegram Stars billed to the user. |
| `tgai_business_revenue_usd_total` | counter | `package` | Stars × USD/star pricing. |
| `tgai_business_payment_events_total` | counter | `event`, `package` | Invoice created, completed, renewal, duplicate. |
| `tgai_business_active_users` | gauge | – | Distinct user IDs seen in the sliding window. |

The `ActiveUserMiddleware` reads `request.state.user_id`,
`X-User-Id`, or `X-Telegram-User-Id` and never blocks a response on a
bookkeeping failure.

## Logging

`app.core.logging.configure_logging` wires structlog with:

* JSON renderer when `LOG_FORMAT=json`, console renderer otherwise.
* Standard processors: timestamp, log level, logger name, stack info on
  errors, request-id contextvars.

Recommended production config: `LOG_FORMAT=json`, `LOG_LEVEL=INFO`. Promtail
parses the JSON and exposes `level`, `event`, `logger`, `request_id`, and
`user_id` as Loki labels (see `deploy/monitoring/loki/promtail-config.yml`).

## SLI / SLO definitions

The on-call rotation defends the following SLOs over a rolling 30-day
window. Burn-rate alerts fire long before the budget is exhausted.

| SLI | Target | Measurement window | Source |
| --- | --- | --- | --- |
| **Availability** | ≥ 99.5% successful responses (status < 500) | 30 days | `http_requests_total` |
| **Read latency** | p95 of GET requests ≤ 500 ms | 30 days, evaluated on 5m windows | `http_request_duration_seconds_bucket` |

Error-budget arithmetic (availability): a 99.5% SLO permits 0.5%
unsuccessful responses, ≈ 3.6 hours of complete outage per 30 days. The
fast-burn page (`BackendAvailabilityFastBurn`) triggers when the 5m & 1h
burn rate exceeds 14.4× budget — at that rate the entire 30-day budget
would be exhausted in ≈ 50 hours, well below the page-worthy threshold.

### Alert routing

All alerts are delivered to the single on-call Telegram chat through the
`telegram-oncall` receiver. The label `severity` selects cadence:

* `severity=page` — group wait 10s, repeat every 1h until acknowledged.
* `severity=ticket` — group wait 1m, repeat every 12h.

Page-severity firings inhibit ticket-severity firings on the same
`alertname`/`service` pair to reduce noise.

## Runbooks

### Availability fast burn

Triggered by `BackendAvailabilityFastBurn`.

1. Open the *SLO* dashboard and confirm the burn rate.
2. Check the *Infrastructure* dashboard for spikes in 5xx by handler.
3. Inspect Sentry for newly grouped errors in the last 15 minutes.
4. Roll back the most recent deploy if it correlates with the spike.
5. If downstream (DB / Redis / Composio / Telegram) is unhealthy, page
   the relevant team and open an incident.

### Availability slow burn

Triggered by `BackendAvailabilitySlowBurn`.

1. File an incident ticket; do not page on-call.
2. Investigate during business hours — usually a slow degradation or a
   noisy endpoint. Use the *Infrastructure* dashboard error-ratio panel
   broken down by `handler` to find the culprit.

### Read latency SLO

Triggered by `BackendReadLatencyP95High`.

1. Open the *Infrastructure* dashboard and inspect p95 by handler.
2. Correlate with DB / Redis latency in the same window (run targeted
   `SELECT pg_stat_activity` / Redis `SLOWLOG` checks).
3. Identify whether traffic spiked or a single handler regressed.
4. Roll back or scale up as appropriate.

### Instance down

Triggered by `BackendInstanceDown`.

1. `kubectl -n <ns> get pods -l app.kubernetes.io/component=backend`.
2. Inspect pod events for OOMKilled or crash-loop.
3. Roll back the most recent deploy if the timing matches.
4. Otherwise investigate node health and scale to spare replicas.

### No completed payments for 1h (business hours)

Triggered by `NoPaymentEventsForOneHour`.

1. Verify the Telegram Stars webhook receives traffic
   (`tgai_business_payment_events_total{event="invoice_created"}`).
2. Check the payments worker logs in Loki:
   `{app="telegram-ai-agent", logger=~"app.services.payments.*"}`.
3. If the webhook is firing but the worker is silent, restart the worker
   deployment.
