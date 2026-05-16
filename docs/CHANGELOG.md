# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Tag a release with `git tag vMAJOR.MINOR.PATCH && git push origin vMAJOR.MINOR.PATCH` —
the [`Release`](../.github/workflows/release.yml) workflow extracts the
matching section from this file into the GitHub Release body, so an
empty section silently drops notes from the release page.

## [Unreleased]

### Added

- Documentation bundle (`docs/USER_GUIDE.md`, `docs/ADMIN_GUIDE.md`)
  and a refreshed `docs/API_REFERENCE.md` that points at the OpenAPI
  artifact for the machine-readable contract.
- OpenAPI generation workflow (`.github/workflows/openapi.yml`) that
  builds `backend/openapi.json` on every push and uploads it as a CI
  artifact (also attached to release tags).
- Launch checklist (`docs/LAUNCH_CHECKLIST.md`) mapping each Phase 4
  acceptance criterion to a concrete operator action.
- BotFather configuration script (`scripts/configure_botfather.py`):
  idempotent `setMyCommands` / `setMyDescription` /
  `setMyShortDescription` / `setChatMenuButton` with per-locale
  fan-out, a `getMe` sanity check and a dry-run mode.
- Production smoke-test script (`scripts/launch_smoketest.py`) that
  drives `/health`, `/balance` and a real Stars `create-invoice` /
  `status` polling cycle to gate the public announcement.
- k6 launch scenario (`loadtest/production_100u.js`) — 100 concurrent
  users / 10 min mix of read / write / invoice creates with per-op
  SLO thresholds.
- Closed beta program runbook (`docs/BETA_PROGRAM.md`) with cohort
  sizing, invite mechanics, survey schema, triage SLAs and exit
  criteria, plus a beta-report template under
  `docs/templates/BETA_REPORT.template.md`.
- Alternative payment rails design (`docs/PAYMENTS_ALT.md`) — TON and
  Stripe behind feature flags, with the schema implications and a
  staged roll-out plan.
- Marketing kit (`docs/marketing/`) with Russian + English launch
  copy, taglines, FAQ and a press-kit asset checklist.
- Post-launch monitoring plan (`docs/POST_LAUNCH.md`) — 72-hour
  watch schedule, dashboards, alerting tree and incident severity
  definitions.
- Production deploy runbook (`docs/PRODUCTION_DEPLOY.md`) covering
  pre-launch gates, the helm-driven cutover and the rollback path.

### Changed

- `loadtest/README.md` now indexes the launch scenario alongside the
  existing read / mixed load tests.

## [1.0.0] — TBD

> First public release of the Telegram AI Agent. Snapshot of the
> Phase 1–4 work that ships once the launch checklist clears.

### Added

- **Phase 1 — MVP core.**
  - FastAPI backend with structlog JSON logs, health checks and
    Docker images.
  - PostgreSQL schema (users, tokens, transactions, audit logs) with
    Alembic migrations.
  - Telegram bot integration: `/start`, `/balance`, `/help`,
    `/profile`, `/referral`.
  - Token Management System with idempotent spend, refund and audit
    rows.
  - Composio MCP integration for Gemini / Claude / GPT.
  - Auth & authorization for users (WebApp `initData` HMAC) and
    admins (JWT + 2FA).
- **Phase 2 — features.**
  - Telegram Stars payments (`XTR`), Pro subscription renewal,
    idempotent webhook handling.
  - Image generation, video generation, text generation, voice
    transcription, document analysis and web search.
  - Rate limiting and per-tariff quotas.
  - Telegram Mini App (React 18 + Vite + TypeScript strict) with
    chat UI, balance, payment flow, profile and history.
  - Referral system and daily bonus streak end-to-end.
- **Phase 3 — admin & polish.**
  - Admin CRM dashboard (Next.js 14) with KPIs, charts and live
    feed.
  - User management (search, detail drawer, CSV export, audit log).
  - Dynamic pricing editor, history feed and overrides applied at
    invoice time.
  - Analytics (revenue, funnel, retention, LTV, token mix), daily
    snapshot worker and CSV export.
  - Broadcast composer, delivery worker and audience preview.
  - System settings dashboard (maintenance, limits, Composio,
    admins) and content editors (prompts, FAQ, welcomes).
- **Phase 4 — production.**
  - Helm chart, Argo Rollouts canary, cert-manager,
    sealed-secrets / external-secrets manifests.
  - Docker Compose fallback for single-host deploys with the Caddy
    edge.
  - Backup CronJobs (Postgres / Redis / media to S3), restore
    runbook and CI checks.
  - Observability stack (Prometheus + Loki + Grafana + Sentry) with
    business KPIs, infra metrics and SLO dashboards.
  - Security audit: STRIDE threat model, OWASP Top-10 mapping,
    pentest scope, PII scrubber and CI scanner gates.
  - GDPR compliance: data export, account deletion with 30-day
    grace, age-verification stub, cookie banner, Privacy Policy /
    ToS / DPA / Subprocessor list.
  - Performance tuning: PostgreSQL pool + statement cache, Redis
    balance cache (write-through), pricing TTL cache, mini-app
    bundle splitting.

### Operational baseline

- Read p95 < 500 ms, write p95 < 2 s, 99.9 % monthly availability
  defended by Prometheus alerts and the on-call rotation.
- Token economy priced at ~50 % of comparable Telegram AI bots
  (`docs/PRICING_STRATEGY.md`).
- All public endpoints documented in `docs/API_REFERENCE.md`; full
  architecture in `docs/ARCHITECTURE.md`.

[Unreleased]: https://github.com/labtgbot/telegram-ai-agent/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/labtgbot/telegram-ai-agent/releases/tag/v1.0.0
