# Code Audit — Issue #136

Full-logic audit of the Telegram AI Agent platform (backend, Mini App, admin
dashboard, infrastructure). This report enumerates every substantive flaw, bug
and vulnerability found, each of which is tracked as a **separate GitHub issue**
with area tags and a remediation stage, so the team can implement the fixes step
by step.

> Scope audited: `backend/` (~27k LOC Python, FastAPI), `mini-app/` (React/Vite
> Telegram WebApp), `admin-dashboard/` (Next.js), and `docker/`, `deploy/`,
> `.github/`, `scripts/` infrastructure.

## Tracking

Every finding is filed as its own GitHub issue with area labels, a complexity
label and a remediation-stage label (`stage-0-blocker` … `stage-3-low`). They are
grouped under the tracking epic **#173**. Finding `#NN` in the table below maps to
GitHub issue **#(137 + NN)** (finding 01 → issue #138 … finding 35 → issue #172).

## Findings summary

Total findings: **35** — **CRITICAL**: 2, **HIGH**: 10, **MEDIUM**: 18, **LOW**: 5.

The highest-impact issues are cross-corroborated and re-verified against the
source (e.g. `request.state.user` is never set → rate limiting collapses to a
spoofable anonymous bucket; the admin dashboard signs JWTs with a committed
`change-me` fallback; `token_usage_logs` runs out of partitions ~2 months after
deploy).

| # | Finding | Severity | Area | Stage | Detail |
|---|---------|----------|------|-------|--------|
| #01 | Admin dashboard signs/verifies JWTs with hardcoded fallback secret `change-me` | CRITICAL | `admin-dashboard` | Stage 0 | [body](findings/01-admin-jwt-default-secret.md) |
| #02 | `token_usage_logs` partition exhaustion — INSERTs fail ~2 months after deploy | CRITICAL | `backend` | Stage 0 | [body](findings/02-token-usage-partition-exhaustion.md) |
| #03 | Per-user rate limiting is bypassed — `request.state.user` is never set | HIGH | `backend` | Stage 1 | [body](findings/03-rate-limit-state-user-never-set.md) |
| #04 | Telegram webhook signature verification disabled by default with no production guard | HIGH | `backend` | Stage 1 | [body](findings/04-webhook-secret-no-prod-guard.md) |
| #05 | Bot chat commands bypass rate limiting entirely | HIGH | `backend` | Stage 1 | [body](findings/05-bot-bypasses-rate-limit.md) |
| #06 | `X-Forwarded-For` trusted unconditionally → rate-limit evasion + forged audit IPs | HIGH | `backend` | Stage 1 | [body](findings/06-xforwarded-for-trusted.md) |
| #07 | Account-deletion worker: one failure rolls back the whole GDPR batch | HIGH | `backend` | Stage 1 | [body](findings/07-account-deletion-batch-rollback.md) |
| #08 | Stale balance cache after a successful Stars purchase (pending branch) | HIGH | `backend` | Stage 1 | [body](findings/08-stale-balance-cache-after-purchase.md) |
| #09 | Model/migration drift drops payment-idempotency & welcome-uniqueness in model-built schemas | HIGH | `backend` | Stage 1 | [body](findings/09-model-migration-drift.md) |
| #10 | Mini App calls non-existent backend routes (profile / delete-account / data-export broken) | HIGH | `mini-app` | Stage 1 | [body](findings/10-miniapp-broken-routes.md) |
| #11 | `compose.prod.yml` runs as root, no resource limits, Redis without auth, mutable `:latest` tags | HIGH | `devops` | Stage 1 | [body](findings/11-compose-prod-hardening.md) |
| #12 | `.trivyignore` waives 14 Next.js CVEs citing a mitigation (admin IP-allowlist) that isn't deployed | HIGH | `devops` | Stage 1 | [body](findings/12-trivyignore-false-mitigation.md) |
| #13 | No brute-force throttle on admin login; attempt counter is resettable | MEDIUM | `backend` | Stage 2 | [body](findings/13-admin-login-no-bruteforce-throttle.md) |
| #14 | CSV/formula injection in admin user export | MEDIUM | `backend` | Stage 2 | [body](findings/14-csv-formula-injection.md) |
| #15 | Telegram initData accepted via URL query parameter (credential leaks to logs) | MEDIUM | `backend` | Stage 2 | [body](findings/15-initdata-in-query-param.md) |
| #16 | Admin audit log readable by the least-privileged `analyst` role | MEDIUM | `backend` | Stage 2 | [body](findings/16-audit-log-readable-by-analyst.md) |
| #17 | Concurrent daily-bonus claim raises 500 instead of AlreadyClaimed and poisons the session | MEDIUM | `backend` | Stage 2 | [body](findings/17-daily-bonus-concurrent-500.md) |
| #18 | Write-through balance cache can serve uncommitted / rolled-back balances | MEDIUM | `backend` | Stage 2 | [body](findings/18-writethrough-cache-uncommitted.md) |
| #19 | TOCTOU pre-check in AI generation services burns provider cost under concurrency | MEDIUM | `backend` | Stage 2 | [body](findings/19-toctou-generation-precheck.md) |
| #20 | Broadcast worker lacks row claiming → duplicate sends under overlapping runs | MEDIUM | `backend` | Stage 2 | [body](findings/20-broadcast-no-row-claiming.md) |
| #21 | No webhook `update_id` idempotency → double side effects on Telegram redelivery | MEDIUM | `backend` | Stage 2 | [body](findings/21-webhook-update-id-idempotency.md) |
| #22 | Broadcast 429 backoff is single-shot → drops recipients during sustained flood limit | MEDIUM | `backend` | Stage 2 | [body](findings/22-broadcast-429-single-shot.md) |
| #23 | Admin dashboard open redirect via protocol-relative `from` parameter | MEDIUM | `admin-dashboard` | Stage 2 | [body](findings/23-admin-open-redirect.md) |
| #24 | Admin middleware role map omits `/system` and `/content` (default to analyst) | MEDIUM | `admin-dashboard` | Stage 2 | [body](findings/24-admin-middleware-role-gaps.md) |
| #25 | Admin auth verify/refresh persist tokens without validating the upstream payload | MEDIUM | `admin-dashboard` | Stage 2 | [body](findings/25-admin-token-persist-no-validation.md) |
| #26 | Mini App swallows API errors (no auth vs diagnostic distinction) | MEDIUM | `mini-app` | Stage 2 | [body](findings/26-miniapp-error-swallowing.md) |
| #27 | Mini App chat never refreshes the displayed balance after token spend | MEDIUM | `mini-app` | Stage 2 | [body](findings/27-miniapp-balance-not-refreshed.md) |
| #28 | Alembic autogenerate lacks a partition guard → may emit destructive drops | MEDIUM | `backend` | Stage 2 | [body](findings/28-alembic-autogenerate-partition-guard.md) |
| #29 | Secret-scan gaps: over-broad gitleaks allowlist + `npm audit --audit-level=critical` | MEDIUM | `devops` | Stage 2 | [body](findings/29-secret-scan-gaps.md) |
| #30 | Monitoring stack ships Grafana `admin/admin` and unauthenticated Prometheus/Alertmanager/Loki | MEDIUM | `devops` | Stage 2 | [body](findings/30-monitoring-default-creds.md) |
| #31 | Auth hardening: non-constant-time webhook compare, TOTP replay window, admin enumeration | LOW | `backend` | Stage 3 | [body](findings/31-auth-hardening-bundle.md) |
| #32 | Admin middleware leaks `x-admin-role` / `x-admin-sub` response headers | LOW | `admin-dashboard` | Stage 3 | [body](findings/32-admin-role-headers-leak.md) |
| #33 | Redundant indexes on `users.telegram_id`/`referral_code`; `usage_log_id` has no FK | LOW | `backend` | Stage 3 | [body](findings/33-db-index-hygiene.md) |
| #34 | Mini App retries 4xx requests and ships source maps to production | LOW | `mini-app` | Stage 3 | [body](findings/34-miniapp-frontend-hygiene.md) |
| #35 | CI supply-chain: third-party actions pinned to mutable tags; kubeval `continue-on-error` | LOW | `devops` | Stage 3 | [body](findings/35-ci-supply-chain.md) |

## Remediation stages

- **Stage 0 — Blocker (fix before any production deploy)** — deploy-blocking; forgeable admin auth and a table that stops
  accepting inserts in production.
- **Stage 1 — High priority (security / data-integrity)** — security and data-integrity defects that should be fixed next.
- **Stage 2 — Medium priority (correctness / hardening)** — correctness and hardening defects.
- **Stage 3 — Low priority (hygiene / defence-in-depth)** — hygiene and defence-in-depth.

## Methodology

Each subsystem was audited independently (auth/security, HTTP API, services &
billing, bot & workers, data/migrations, Mini App, admin dashboard, devops). Only
findings at MEDIUM+ confidence are reported; the highest-severity ones were
re-verified by reading the cited source. Each finding records exact `file:line`
evidence, concrete impact, a suggested fix and acceptance criteria.

See the individual files in [`findings/`](findings/) for full write-ups; each maps
1:1 to a GitHub issue.
