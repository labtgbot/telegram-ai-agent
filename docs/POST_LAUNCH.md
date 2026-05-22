# Post-Launch Monitoring Plan — v1.0.0

The first three days after the public announcement are the
highest-signal window the team will get for production behaviour. This
runbook locks in **what** to watch, **when** to watch it and **how**
to respond. It picks up the moment the cutover (see
[`docs/PRODUCTION_DEPLOY.md`](PRODUCTION_DEPLOY.md)) hands the bot to
comms and ends after the 72-hour watch closes.

The base monitoring contract is unchanged from steady state — see
[`docs/MONITORING.md`](MONITORING.md) for the metrics, alerts and
dashboards. This document is the **launch-specific overlay**.

---

## 1. Watch schedule (T+0 → T+72h)

| Window         | Cadence            | Primary watcher  | Secondary       | Notes                                        |
|----------------|--------------------|------------------|-----------------|----------------------------------------------|
| T+0 → T+1h     | Continuous         | Release manager  | Primary on-call | Sit in front of Grafana SLO + Business.      |
| T+1h → T+6h    | Every 15 min       | Primary on-call  | Comms lead      | First spike from the announcement lands here.|
| T+6h → T+24h   | Every 30 min       | Primary on-call  | Secondary on-call | Cover the EU evening + US peak.             |
| T+24h → T+48h  | Every hour         | Secondary on-call | Backend lead    | First quiet diurnal cycle.                   |
| T+48h → T+72h  | Every 2 hours      | Secondary on-call | Backend lead    | Hand-off to steady-state monitoring.         |

Watch closes when the **T+72h** review (§5) signs off all exit
criteria. After that the on-call rotation switches to the standard
12-hour shifts described in `docs/MONITORING.md`.

Each watcher posts an inline summary in the launch chat at the end of
their shift: top-3 metric movements, any alerts, any user reports
forwarded from comms. Five lines or less; the goal is a continuous
written trail without a hand-off meeting.

---

## 2. Dashboards to babysit

Open these as separate browser tabs for the duration of T+0 → T+6h.

| Dashboard                    | What it tells you                                                 |
|------------------------------|-------------------------------------------------------------------|
| Grafana → **SLO**            | Read p95, write p95, error-budget burn, availability ratio.       |
| Grafana → **Business**       | `tokens_sold_total`, `revenue_stars_total`, `payment_events_total`.|
| Grafana → **Infra**          | Pod CPU / RSS, HPA replicas, Postgres connections, Redis hit rate.|
| Sentry → **Releases**        | Issue count tagged `release=telegram-ai-agent-backend@1.0.0`.     |
| Sentry → **Releases (web)**  | Mini-app issues for `release=miniapp@1.0.0`.                      |
| Loki via Grafana **Explore** | `{job="telegram-ai-agent-backend"} |= "ERROR"`.                   |
| Telegram chat                | The on-call chat receives every Alertmanager page.                |

Pin them as a Grafana playlist so the secondary watcher can rotate
through without clicking around.

---

## 3. Watch metrics — green / yellow / red

Each watcher checks the same nine numbers per cadence. Anything in
**yellow** triggers a written note in the launch chat; anything in
**red** triggers the matching response in §4.

| # | Metric                                              | Green        | Yellow            | Red                |
|---|-----------------------------------------------------|--------------|-------------------|--------------------|
| 1 | `http_req_duration` read p95 (5 min)                | < 400 ms     | 400–500 ms        | > 500 ms for 10 m  |
| 2 | `http_req_duration` write p95 (5 min)               | < 1.5 s      | 1.5–2 s           | > 2 s for 10 m     |
| 3 | 5xx ratio (5 min)                                   | < 0.5 %      | 0.5–2 %           | > 2 % for 5 m      |
| 4 | `payment_events_total{event="successful_payment"}`  | rate ≥ baseline 0.8× | 0.5×–0.8× | < 0.5× for 30 m    |
| 5 | `payment_events_total{event="failed"}` rate         | < 5 % of total | 5–10 %         | > 10 % for 15 m    |
| 6 | `active_users` (5-min sliding)                      | rising       | flat 30 m         | down >50 % from prev hour |
| 7 | Postgres connection pool usage                      | < 70 %       | 70–90 %           | > 90 % for 5 m     |
| 8 | Redis evictions / s                                 | 0            | spikes < 60 s     | sustained > 0      |
| 9 | Sentry new-issue rate per release                   | < 5 / h      | 5–20 / h          | > 20 / h           |

The numbers come from the existing `business.json`, `infra.json`,
`slo.json` Grafana dashboards — no new instrumentation is required.

---

## 4. Alerting tree

The alerts themselves are defined in
[`deploy/monitoring/prometheus/rules/slo-alerts.yml`](../deploy/monitoring/prometheus/rules/slo-alerts.yml)
and routed through
[`deploy/monitoring/alertmanager/alertmanager.yml`](../deploy/monitoring/alertmanager/alertmanager.yml).
The launch overlay does **not** add new alerts — the rules below
describe the human escalation path on top of the existing routing.

```
Prometheus rule fires
        │
        ▼
Alertmanager  ──► Telegram on-call chat
        │
        ├── severity=page  ──► Primary on-call: 5-min response SLA
        │                     │
        │                     └── No ack in 10 min ──► Secondary on-call paged
        │                                              │
        │                                              └── No ack in 10 min ──► Release manager
        │
        └── severity=ticket ──► Primary on-call: 30-min ack, file ticket
```

During the launch watch the response SLAs tighten:

| Severity | Steady state | Launch (T+0 → T+72h) |
|----------|--------------|----------------------|
| page     | 15 min ack   | **5 min ack**        |
| ticket   | 2 h ack      | **30 min ack**       |

Escalation contacts are listed in the internal ops handbook — do not
commit them to the repo.

---

## 5. Incident severities

These severities apply to **user-impacting** issues discovered during
the watch. They are the same set the on-call rotation uses afterwards,
documented here so the launch ticket can reference them.

| Sev | User impact                                            | Examples                                                                 | Response                                                                 |
|-----|--------------------------------------------------------|--------------------------------------------------------------------------|--------------------------------------------------------------------------|
| S0  | Bot unavailable or payments completely broken          | Webhook returns 5xx for > 5 min; Stars charges debit without credit.     | Page on-call. Roll back per [`PRODUCTION_DEPLOY.md`](PRODUCTION_DEPLOY.md) §6. Announce in public Telegram channel. |
| S1  | Major feature degraded, no good workaround             | Image generation 5xx > 50 %, Mini App white-screens for > 10 % of users. | Page on-call. Triage within 30 min. Status post within 1 h.              |
| S2  | Minor degradation, workaround exists                   | Daily-bonus claim throws an error but balance still updates manually.    | Ticket on-call. Fix in the next backend deploy.                          |
| S3  | Cosmetic or low-frequency                              | Typo in `/help`, slow image preview on Android < 8 % of users.           | File issue, no on-call action.                                           |

The **S0 trigger list** is intentionally short and matches the
rollback triggers in [`PRODUCTION_DEPLOY.md`](PRODUCTION_DEPLOY.md) §6
— anything outside that list is at most an S1 and never blocks the
launch on its own.

---

## 6. Capacity & cost watch

The HPA targets in `values-production.yaml` are sized for 100
concurrent users plus a 2× headroom. Beyond that, the launch watch
also monitors the bill so cost surprises do not slip past the SLO
dashboard.

| Signal                              | Source                                         | Threshold for review              |
|-------------------------------------|------------------------------------------------|-----------------------------------|
| Backend pod count                   | `kube_horizontalpodautoscaler_status_current_replicas` | > 70 % of `maxReplicas` for 30 m |
| AI provider spend (per hour)        | Composio + provider billing dashboards         | 2× the staging baseline           |
| Telegram Stars revenue (per hour)   | Business dashboard `revenue_stars_total`       | < 0.5× expected from beta volume  |
| S3 backup size growth               | `backup-verify` CronJob log                    | > 20 % vs. yesterday              |

The capacity row is a **scale-up trigger**, not an alert — if it fires
twice in a 6-hour window, bump `backend.maxReplicas` in the next
release.

---

## 7. Exit criteria — closing the watch (T+72h)

The launch watch closes when **all** are true:

- [ ] No S0 or S1 incidents in the last 24 hours.
- [ ] SLO dashboard: read p95 < 500 ms, write p95 < 2 s for 24 h.
- [ ] Error budget burn < 1× for the full 72-hour window.
- [ ] Payments dashboard shows ≥ 50 completed transactions across at
      least 25 distinct users (post-beta cohort).
- [ ] No open `BackendAvailabilityFastBurn` or
      `BackendAvailabilitySlowBurn` alerts.
- [ ] Sentry top-issues triaged (resolved, suppressed or scheduled).
- [ ] Capacity rows §6 all green or scheduled.

The release manager files the launch report under
`docs/launch-reports/` (template below) and closes the watch ticket.

Suggested report structure:

```
docs/launch-reports/v1.0.0-launch.md
  1. Summary           — image tag, dates, who ran what.
  2. Timeline          — cutover → watch close.
  3. Metrics snapshot  — Grafana screenshots at T+0, T+24h, T+72h.
  4. Incidents         — every Sev S2+ that opened during the watch.
  5. Action items      — follow-up tickets created.
  6. Sign-off          — release manager, on-call, comms lead.
```

The report is the artefact comms / leadership ask for; the rest of
the codebase has no dependency on it, but the next launch will read
it first.
