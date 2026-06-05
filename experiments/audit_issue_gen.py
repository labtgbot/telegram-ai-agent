#!/usr/bin/env python3
"""Generator for the issue #136 code-audit deliverable.

Produces:
  docs/audit/README.md            -- master index / audit report
  docs/audit/findings/NN-*.md     -- one professional issue body per finding

And prints, to stdout, a JSON manifest used by create_issues.py to open the
GitHub issues with the correct labels.

The findings below were produced by a subsystem-by-subsystem audit and the
highest-impact ones were independently re-verified against the source tree
(see file:line references).
"""
from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "audit"
FIND = OUT / "findings"

# Remediation stages (used as "stages of implementation" requested in #136).
STAGES = {
    0: "Stage 0 — Blocker (fix before any production deploy)",
    1: "Stage 1 — High priority (security / data-integrity)",
    2: "Stage 2 — Medium priority (correctness / hardening)",
    3: "Stage 3 — Low priority (hygiene / defence-in-depth)",
}

# Each finding: (num, slug, title, severity, confidence, stage, complexity,
#                labels, area, body_sections)
# body_sections is a dict with keys: summary, evidence, impact, fix, acceptance
Finding = dict


def f(num, slug, title, severity, confidence, stage, complexity, labels, area,
      summary, evidence, impact, fix, acceptance) -> Finding:
    return dict(num=num, slug=slug, title=title, severity=severity,
                confidence=confidence, stage=stage, complexity=complexity,
                labels=labels, area=area, summary=summary, evidence=evidence,
                impact=impact, fix=fix, acceptance=acceptance)


FINDINGS: list[Finding] = [
    # ===================== CRITICAL / Stage 0 =====================
    f(1, "admin-jwt-default-secret",
      "[SEC][CRITICAL] Admin dashboard signs/verifies JWTs with hardcoded fallback secret `change-me`",
      "CRITICAL", "HIGH", 0, "complexity-low",
      ["bug", "security", "admin-crm"], "admin-dashboard",
      "The Next.js admin dashboard falls back to a publicly-known signing secret when "
      "`ADMIN_JWT_SECRET` is unset, and — unlike the Python backend — has no production "
      "guard that refuses to start with the placeholder.",
      "`admin-dashboard/lib/env.ts:15`\n"
      "```ts\njwtSecret: process.env.ADMIN_JWT_SECRET ?? \"change-me\",\n```\n"
      "`lib/auth/tokens.ts` verifies admin access tokens with `serverEnv().jwtSecret`. "
      "The repo even ships `admin-dashboard/scripts/dev-token.mjs` which mints a valid "
      "`super_admin` token using the same default. The Python backend protects against "
      "this via `assert_production_safe` (`backend/app/core/config.py:333-353`) but the "
      "Node side has no equivalent.",
      "Anyone who knows the committed default secret can forge a `super_admin` access "
      "token, set the `admin_access_token` cookie, pass middleware verification and gain "
      "full admin-UI access (user bans, token grants, pricing, broadcasts, admin-role "
      "management). If the backend shares the same fallback secret, this is a complete "
      "authentication bypass of the admin surface.",
      "Remove the `?? \"change-me\"` fallback. Throw at module load / server start when "
      "`ADMIN_JWT_SECRET` is unset or equals `change-me` while `NODE_ENV === \"production\"`, "
      "mirroring the backend's fail-closed behaviour. Require a high-entropy secret.",
      ["`serverEnv()` throws in production when `ADMIN_JWT_SECRET` is missing or equals the placeholder.",
       "A forged token signed with `change-me` is rejected by middleware in a production build.",
       "`dev-token.mjs` only works against a dev environment / explicit dev secret.",
       "Regression test covers the production-guard path."]),

    f(2, "token-usage-partition-exhaustion",
      "[DATA][CRITICAL] `token_usage_logs` partition exhaustion — INSERTs fail ~2 months after deploy",
      "CRITICAL", "HIGH", 0, "complexity-medium",
      ["bug", "database", "backend"], "backend",
      "The partitioned `token_usage_logs` table is created with only two month partitions "
      "and no DEFAULT partition, and the monthly rotation job promised in the migration "
      "comment does not exist.",
      "`backend/alembic/versions/20260515_0001_baseline_initial_schema.py:142-194` creates "
      "the RANGE-partitioned parent plus only the current and next month partitions. The "
      "comment references a \"ежемесячный Celery beat job\" for rotation, but "
      "`backend/app/workers/` contains only `account_deletion, broadcast, daily_analytics, "
      "subscriptions, video_polling` — no partition manager (verified with grep for "
      "`PARTITION OF` / `CREATE TABLE token_usage_logs_`).",
      "`TokenUsageLog` is written on every billable action (`token_service.py:381`, "
      "`composio/usage.py:43`). Once `created_at` passes the end of the second pre-created "
      "month, every INSERT raises `no partition of relation \"token_usage_logs\" found for "
      "row`, breaking the core token-accounting / usage-logging path in production.",
      "Ship a scheduled job (or migration-managed pg_partman) that pre-creates upcoming "
      "monthly partitions ahead of time, and add a `DEFAULT` partition as a safety net so "
      "inserts never hard-fail.",
      ["A worker/cron pre-creates the next N monthly partitions and is covered by a test.",
       "A `DEFAULT` partition exists so an INSERT past the last partition still succeeds.",
       "An integration test inserts a row dated 3+ months out and it succeeds."]),

    # ===================== HIGH / Stage 1 =====================
    f(3, "rate-limit-state-user-never-set",
      "[SEC][HIGH] Per-user rate limiting is bypassed — `request.state.user` is never set",
      "HIGH", "HIGH", 1, "complexity-low",
      ["bug", "security", "backend"], "backend",
      "Every authenticated request is rate-limited as an anonymous IP bucket because the "
      "Telegram init-data auth dependency never writes `request.state.user`, which the "
      "limiter (and the active-user metric) rely on.",
      "`backend/app/api/rate_limit.py:125-131`\n"
      "```python\nuser = getattr(request.state, \"user\", None)\nif user is not None:\n    "
      "plan = await resolve_plan_for_user(session, user)\n    identifier = str(user.telegram_id)\n"
      "else:\n    plan = PLAN_ANONYMOUS\n    identifier = f\"ip:{_client_ip(request)}\"\n```\n"
      "`backend/app/auth/dependencies.py:108-159` (`get_current_user_from_init_data`) returns "
      "the user but never sets `request.state.user` / `request.state.user_id`. A repo-wide grep "
      "confirms `request.state.user` is only ever *read*. The `anonymous` plan defines only "
      "`per_hour=5` and none of the per-media (`image_per_day`, `video_per_day`, …) buckets, "
      "and `RateLimitConfig.rules_for` silently skips undefined keys.",
      "All per-plan daily caps and all per-media caps are never enforced for real users — the "
      "expensive AI generation endpoints are effectively unthrottled (only a shared 5/hour "
      "anonymous bucket applies, itself bypassable — see finding on `X-Forwarded-For`). Paying "
      "users are wrongly throttled to the anonymous bucket shared per IP. The active-user "
      "metric (`metrics.py:273`, expects `request.state.user_id`) is also undercounted.",
      "Set `request.state.user = user` (and `request.state.user_id = user.id`) inside "
      "`get_current_user_from_init_data` before returning, and ensure the auth dependency is "
      "resolved before the rate-limit dependency runs. Add a regression test asserting an "
      "authenticated generate request is bucketed under the user's plan.",
      ["Authenticated generate requests are bucketed by the user's plan, not `anonymous`.",
       "Per-plan and per-media daily caps are enforced for authenticated users.",
       "Active-user metric increments for authenticated requests.",
       "Regression test covers plan resolution for an authenticated caller."]),

    f(4, "webhook-secret-no-prod-guard",
      "[SEC][HIGH] Telegram webhook signature verification disabled by default with no production guard",
      "HIGH", "HIGH", 1, "complexity-low",
      ["bug", "security", "telegram", "backend"], "backend",
      "`telegram_webhook_secret` defaults to empty (verification disabled) and the production "
      "safety check does not require it, so a misconfigured deploy accepts forged Telegram "
      "updates from anyone.",
      "`backend/app/api/v1/bot.py:68-75`\n"
      "```python\ndef _check_secret(expected, received):\n    if not expected:\n        return  "
      "# secret disabled in this environment\n    if not received or received != expected:\n        "
      "raise HTTPException(401, \"invalid_webhook_secret\")\n```\n"
      "`backend/app/core/config.py:120` sets `telegram_webhook_secret` default `\"\"`, and "
      "`assert_production_safe` (`config.py:333-353`) only validates `admin_jwt_secret` — it "
      "does not require the webhook secret. The comparison also uses `!=` rather than "
      "`hmac.compare_digest`.",
      "With the default config anyone who knows the webhook URL can POST forged updates: "
      "impersonate arbitrary `from.id`/`chat.id`, trigger `/start` with attacker-chosen referral "
      "payloads, claim daily bonuses, and drive paid AI generation. (`successful_payment` is "
      "separately validated, but the registration/bonus/generation surface is fully spoofable.)",
      "Require a non-empty `telegram_webhook_secret` in production by extending "
      "`assert_production_safe`, fail closed when missing, and replace `!=` with "
      "`hmac.compare_digest`.",
      ["`assert_production_safe` fails when the webhook secret is empty outside dev/test.",
       "Webhook secret comparison uses `hmac.compare_digest`.",
       "A request with a missing/incorrect secret is rejected in a production config (test)."]),

    f(5, "bot-bypasses-rate-limit",
      "[SEC][HIGH] Bot chat commands bypass rate limiting entirely",
      "HIGH", "HIGH", 1, "complexity-medium",
      ["bug", "security", "telegram", "backend"], "backend",
      "AI generation triggered through the Telegram chat (`/ask`, `/agent`, `/image`, `/video`, "
      "free-text) calls the generation services directly without invoking the rate limiter, so "
      "the chat path has no hourly/daily/per-action quota at all.",
      "Handlers `handle_image` (`backend/app/bot/handlers.py:321`), `handle_video` (`:483`) and "
      "`_run_text_mode` (`:643`) call the generation services but never call `RateLimiter.consume`. "
      "The webhook route (`backend/app/api/v1/bot.py:78-114`) has no `rate_limit` dependency and "
      "`dispatch_update` never invokes the limiter. The only consumer of `RateLimiter` is "
      "`backend/app/api/rate_limit.py`. The bot-side helper `backend/app/bot/rate_limit.py` "
      "(`format_rate_limit_message`, `upgrade_keyboard`) is dead code.",
      "A user driving generation through chat is subject to no quota — only token balance brakes "
      "them, and free signup/daily/referral bonuses make abuse of provider/Composio spend and "
      "Telegram send budget realistic. The Mini App path is protected; the chat path is not.",
      "In `_run_text_mode`, `handle_image`, `handle_video`, resolve the user's plan and call "
      "`RateLimiter(...).consume(plan=..., identifier=str(telegram_id), action=...)` before "
      "invoking generation; on `RateLimitedError` reply using the existing "
      "`format_rate_limit_message` / `upgrade_keyboard` helpers.",
      ["Bot image/video/text generation enforces the same per-plan quotas as the HTTP endpoints.",
       "A rate-limited chat request replies with the upgrade message instead of generating.",
       "Tests cover the chat rate-limit path for at least image and text."]),

    f(6, "xforwarded-for-trusted",
      "[SEC][HIGH] `X-Forwarded-For` trusted unconditionally → rate-limit evasion + forged audit IPs",
      "HIGH", "HIGH", 1, "complexity-medium",
      ["bug", "security", "backend"], "backend",
      "The client-IP helper takes the first `X-Forwarded-For` hop verbatim with no trusted-proxy "
      "allowlist; the value is used both as the anonymous rate-limit bucket key and as the source "
      "IP recorded in admin audit logs.",
      "`backend/app/api/rate_limit.py:70-85` returns `fwd.split(\",\",1)[0].strip()` with no "
      "validation. `main.py` configures no `ProxyHeadersMiddleware`/trusted-host. The same "
      "`x-forwarded-for.split(\",\")[0]` pattern records audit IPs in `admin_users.py:242`, "
      "`admin_analytics.py:61`, `admin_pricing.py:185`, `admin_content.py:84`, "
      "`admin_system.py:65`, `admin_broadcasts.py:179`.",
      "Combined with the `request.state.user` bug, the only enforced limit (anonymous per-IP) is "
      "trivially defeated by sending a random `X-Forwarded-For` per request. Audit-log IP fields "
      "can be forged, undermining forensic value.",
      "Resolve the client IP from the right-most untrusted hop using a configured trusted-proxy "
      "count (or `uvicorn --forwarded-allow-ips` / Starlette `ProxyHeadersMiddleware`). Never "
      "trust the left-most XFF entry directly. Reuse the corrected helper for audit IP capture.",
      ["Client IP is derived only from trusted proxies (configurable).",
       "Spoofing `X-Forwarded-For` no longer yields a fresh rate-limit bucket (test).",
       "Audit logs record the real peer IP."]),

    f(7, "account-deletion-batch-rollback",
      "[BUG][HIGH] Account-deletion worker: one failure rolls back the whole GDPR batch",
      "HIGH", "HIGH", 1, "complexity-medium",
      ["bug", "backend", "security"], "backend",
      "The account-deletion worker processes all due deletions in one shared session/transaction; "
      "a single failing item poisons the session, discards already-completed anonymisations, and "
      "never persists the FAILED status.",
      "`backend/app/workers/account_deletion.py:44-68` runs the loop on one `session` with a "
      "single `commit()` after the loop. The per-item `except` (`:56-63`) sets "
      "`request.status = FAILED` on the *same* session that already raised; once "
      "`anonymise_user` fails mid-way (e.g. one of the `delete(...)`/`update` in "
      "`account_deletion.py:259-271` errors) the session is in `PendingRollbackError` state, so "
      "the FAILED assignment and the final `commit()` raise and the outer `except` rolls back the "
      "entire pass.",
      "A single problematic user blocks GDPR Art. 17 anonymisation for the whole batch (data that "
      "must be erased remains) and the FAILED status is never recorded, so the poison row blocks "
      "every subsequent run too.",
      "Give each request its own transaction (commit per item, or `session.begin_nested()` "
      "savepoints) and `rollback()` inside the per-item `except` before flipping that single "
      "request to FAILED and committing it, so one failure cannot revert siblings.",
      ["A failing deletion isolates to that request; siblings still complete and commit.",
       "A failed deletion is persisted with FAILED status and an error reason.",
       "A poison row does not block subsequent worker runs (test with a forced failure)."]),

    f(8, "stale-balance-cache-after-purchase",
      "[BUG][HIGH] Stale balance cache after a successful Stars purchase (pending branch)",
      "HIGH", "HIGH", 1, "complexity-low",
      ["bug", "payments", "tokens", "backend"], "backend",
      "The normal one-time Stars purchase path credits the balance in-place and flushes, but "
      "never refreshes the Redis balance cache, so the user keeps seeing their pre-purchase "
      "balance until the TTL expires.",
      "`backend/app/services/payments.py:441-475` — the `pending is not None and not is_recurring` "
      "branch mutates `user.token_balance` directly and `flush()`es but never calls "
      "`token_service._refresh_cache(...)`. The `else` branch (`token_service.add`) does refresh "
      "(`token_service.py:317`). `get_balance` (`token_service.py:182-185`) returns the cached "
      "value first.",
      "After a normal purchase the cached (lower) balance is served until `balance_cache_ttl_seconds`, "
      "so a user who just paid may be wrongly told they have insufficient tokens. The DB is correct; "
      "the cache lies until TTL or the next `TokenService` mutation.",
      "After the in-place credit + flush, call "
      "`await token_service._refresh_cache(user.id, int(user.token_balance))`, or route the credit "
      "through `TokenService.add` consistently with the `else` branch.",
      ["The Redis balance cache reflects the new balance immediately after a Stars purchase.",
       "A regression test asserts the cached balance equals the DB balance post-purchase."]),

    f(9, "model-migration-drift",
      "[DATA][HIGH] Model/migration drift drops payment-idempotency & welcome-uniqueness in model-built schemas",
      "HIGH", "HIGH", 1, "complexity-medium",
      ["bug", "database", "backend"], "backend",
      "Several uniqueness/index objects exist only in migrations and not in the SQLAlchemy models, "
      "so any schema built from `Base.metadata` (tests, `create_all`) silently lacks the guards, "
      "and `alembic --autogenerate` would propose dropping them.",
      "`uq_welcome_messages_active_per_locale` (partial unique) is created in "
      "`20260516_0009_admin_content.py:168-174` but absent from `app/models/welcome_message.py:57-60`. "
      "`uq_transactions_payment_id` (partial unique, payment idempotency) and "
      "`ix_transactions_payment_status` are created in `20260516_0003_payment_idempotency.py:37-49` "
      "but absent from `app/models/transaction.py:58-66`. `ix_transactions_created` differs: model "
      "declares plain ascending (`transaction.py:65`) while migration created it on "
      "`created_at DESC` (`20260515_0001:132-137`).",
      "Schemas built from models (tests, any `create_all` path) lack the welcome-message and "
      "payment-idempotency uniqueness guards, allowing duplicate active welcomes / double-credited "
      "payments in those environments; and `--autogenerate` output is unreliable.",
      "Add the missing `Index(..., unique=True, postgresql_where=...)` declarations to the "
      "`WelcomeMessage` and `Transaction` models so models match migrations, and align the "
      "`ix_transactions_created` definition.",
      ["Models and migrations agree (a fresh `--autogenerate` is empty/no-op).",
       "`create_all`-built schemas include the payment-idempotency and welcome-uniqueness indexes.",
       "A test builds the schema from models and asserts the unique indexes exist."]),

    f(10, "miniapp-broken-routes",
      "[BUG][HIGH] Mini App calls non-existent backend routes (profile / delete-account / data-export broken)",
      "HIGH", "HIGH", 1, "complexity-low",
      ["bug", "frontend"], "mini-app",
      "Three Mini App API calls target paths/methods that do not exist on the backend, so profile "
      "refresh silently fails and the two GDPR-critical actions are completely non-functional while "
      "appearing to work.",
      "`mini-app/src/services/userApi.ts`: `get(\"/users/me\")` (:24), "
      "`post(\"/user/data-export\")` (:38), `delete(\"/user/account\")` (:42). The backend `user` "
      "router exposes `GET /user/me/export` (`user.py:479-480`), `DELETE /user/me` "
      "(`user.py:518-519`) and there is no `/users/me` profile route. `ProfilePage.tsx:42-43` "
      "swallows the 404 silently.",
      "`getProfile()` 404s on every ProfilePage mount (silent). \"Delete account\" and \"Request "
      "data export\" always fail (404/405) — two GDPR-critical actions are broken while looking "
      "functional.",
      "Point the client at `GET /user/me` (or the correct profile route), `DELETE /user/me`, and "
      "`GET /user/me/export`; align HTTP methods. Add tests asserting exact path + method.",
      ["Profile, delete-account and data-export call the real backend routes with correct methods.",
       "Delete-account and data-export succeed end-to-end.",
       "Tests assert the exact path + method for each call."]),

    f(11, "compose-prod-hardening",
      "[DEVOPS][HIGH] `compose.prod.yml` runs as root, no resource limits, Redis without auth, mutable `:latest` tags",
      "HIGH", "HIGH", 1, "complexity-medium",
      ["bug", "devops", "security"], "devops",
      "The documented production-fallback docker-compose stack runs every container as root with no "
      "hardening or resource limits, exposes an unauthenticated Redis on the shared network, and "
      "defaults images to mutable `:latest` tags.",
      "`docker/compose.prod.yml:18-123` — no `user:`, `read_only:`, `cap_drop:`, "
      "`security_opt: [no-new-privileges:true]` or `deploy.resources.limits` on any service "
      "(contrast the hardened Helm chart `backend-deployment.yaml:33-86`). Redis "
      "(`compose.prod.yml:112-123`) runs without `--requirepass`. Images default to "
      "`...:latest` (`:39,71,81`). Healthchecks use `wget` against images that may not bundle it "
      "(`:74-78,89-93`).",
      "A compromise of any container runs as root with full capabilities and no memory cap (one "
      "service can OOM the host; breakout is easier). Any container reaching Redis gets "
      "unauthenticated read/write to session/cache/rate-limit data. `:latest` makes deploys "
      "non-reproducible.",
      "Add `user`, `read_only: true` (+ tmpfs), `cap_drop: [ALL]`, "
      "`security_opt: [no-new-privileges:true]` and `deploy.resources.limits` to each service "
      "(mirror Helm); set `--requirepass ${REDIS_PASSWORD:?}` and include it in `REDIS_URL`; pin "
      "image refs to a version/digest (or make them required); use a base-image-guaranteed "
      "healthcheck with a `start_period`.",
      ["All compose.prod services run non-root with dropped capabilities and resource limits.",
       "Redis requires a password and `REDIS_URL` carries it.",
       "Image tags are pinned (not `:latest`).",
       "Healthchecks use a command guaranteed by the base image."]),

    f(12, "trivyignore-false-mitigation",
      "[DEVOPS][HIGH] `.trivyignore` waives 14 Next.js CVEs citing a mitigation (admin IP-allowlist) that isn't deployed",
      "HIGH", "HIGH", 1, "complexity-medium",
      ["bug", "devops", "security"], "devops",
      "Fourteen HIGH/CRITICAL Next.js advisories are permanently suppressed in the CI security gate "
      "on the basis of an \"ingress IP-allowlist + CSP nonces\" compensating control that does not "
      "exist in the deployment.",
      "`.trivyignore:15-31` (F-006) suppresses CVE-2026-44573 … GHSA-q4gf-8mx6-v5v3 citing the "
      "allowlist. The production ingress (`deploy/helm/telegram-ai-agent/values-production.yaml:133-153`) "
      "sets only body-size/timeouts/limit-rps; a repo-wide search for `whitelist-source-range` / "
      "allowlist annotations returns nothing. The admin host is served with no source-IP restriction.",
      "14 HIGH/CRITICAL Next.js advisories are waived from the CI gate behind a control that was "
      "never deployed, leaving the highest-value target (admin dashboard) exposed to those CVEs.",
      "Either implement the claimed control "
      "(`nginx.ingress.kubernetes.io/whitelist-source-range` on the admin host) or remove the false "
      "justification and prioritise the Next.js upgrade. Do not suppress CVEs behind a non-existent "
      "mitigation.",
      ["Either the IP-allowlist is actually configured on the admin ingress, or the Next.js CVEs "
       "are remediated and the `.trivyignore` entries removed.",
       "`.trivyignore` justifications reference only controls that are actually deployed."]),

    # ===================== MEDIUM / Stage 2 =====================
    f(13, "admin-login-no-bruteforce-throttle",
      "[SEC][MEDIUM] No brute-force throttle on admin login; attempt counter is resettable",
      "MEDIUM", "HIGH", 2, "complexity-medium",
      ["bug", "security", "backend"], "backend",
      "The admin login `request` endpoint has no rate limit and re-issuing a code resets the "
      "verify attempt counter, so the 6-digit code can be brute-forced over time.",
      "`backend/app/api/v1/auth.py:168-197` (request) has no rate-limit dependency and each call "
      "deletes the attempts key (`admin_login.py:101`), resetting the 5-attempt budget in "
      "`verify_admin_login` (`admin_login.py:124-129`). Neither `/auth/admin/login/request` nor "
      "`/auth/admin/login/verify` is IP/identity throttled.",
      "An attacker can repeatedly re-request to reset the attempt budget and brute force the "
      "1e6-space code, and flood the admin via the bot with code messages.",
      "Add IP- and telegram_id-scoped rate limits to both endpoints, and make the attempt counter "
      "independent of code re-issuance (or cap re-requests per window).",
      ["Both admin-login endpoints are rate limited per IP and per telegram_id.",
       "Re-requesting a code does not reset the brute-force attempt budget.",
       "Tests cover lockout after N failed verifications across re-requests."]),

    f(14, "csv-formula-injection",
      "[SEC][MEDIUM] CSV/formula injection in admin user export",
      "MEDIUM", "HIGH", 2, "complexity-low",
      ["bug", "security", "admin-crm", "backend"], "backend",
      "Attacker-controlled Telegram profile fields are written into the admin CSV export without "
      "neutralising leading formula characters.",
      "`backend/app/services/admin_users.py:518-528` (`_csv_row`/`_fmt`) writes `username`, "
      "`first_name`, `last_name` via `csv.writer` with no neutralisation of leading `=`, `+`, `-`, "
      "`@`. These values are user-set via the Telegram profile and enter the DB via "
      "`upsert_telegram_user`.",
      "A user setting their name to e.g. `=HYPERLINK(...)` or `=cmd|'/c calc'!A1` causes formula "
      "execution when an admin opens the export in Excel/LibreOffice/Sheets — data exfiltration or "
      "command execution on the admin's machine.",
      "Sanitise cells beginning with `= + - @` (and control chars) by prefixing a single quote (or "
      "wrapping/escaping), centralised in `_fmt`.",
      ["Exported cells beginning with a formula character are neutralised.",
       "A test exports a user named `=1+1` and asserts the cell is escaped."]),

    f(15, "initdata-in-query-param",
      "[SEC][MEDIUM] Telegram initData accepted via URL query parameter (credential leaks to logs)",
      "MEDIUM", "HIGH", 2, "complexity-low",
      ["bug", "security", "telegram", "backend"], "backend",
      "The init-data auth dependency accepts the credential from the URL query string, so it leaks "
      "into access logs, proxy logs, browser history and `Referer` headers.",
      "`backend/app/auth/dependencies.py:116-119`\n"
      "```python\nraw = x_telegram_init_data or request.query_params.get(\"initData\")\n```\n"
      "Used by `generate.py`, `user.py`, `payment.py`. initData is a bearer-style credential valid "
      "until `telegram_init_data_max_age`.",
      "Leaked initData can be replayed within its validity window. Sensitive-credential-in-URL is "
      "an OWASP-flagged weakness.",
      "Accept initData only from the `X-Telegram-Init-Data` header (and/or POST body). If a "
      "query-param fallback must remain, scope it narrowly and ensure logging redacts `initData`.",
      ["initData is read from the header (and/or body), not the query string.",
       "If a legacy fallback remains, `initData` is redacted from logs.",
       "Tests confirm header-based auth works and query-param is removed/deprecated."]),

    f(16, "audit-log-readable-by-analyst",
      "[SEC][MEDIUM] Admin audit log readable by the least-privileged `analyst` role",
      "MEDIUM", "MEDIUM", 2, "complexity-low",
      ["bug", "security", "admin-crm", "backend"], "backend",
      "The audit-log read endpoint is gated only by `get_current_admin` (ANALYST+), exposing every "
      "admin's source IP and user-agent to the lowest-privileged role while mutations require "
      "support_admin+.",
      "`backend/app/api/v1/admin_users.py` — `list_audit_log_endpoint` depends on "
      "`get_current_admin` (ANALYST floor) whereas write endpoints use "
      "`require_role(SUPPORT_ADMIN)`.",
      "An analyst (intended least-privilege) can enumerate the activity, IPs and UAs of "
      "super_admin/support_admin accounts — reconnaissance for targeting higher-privileged admins.",
      "Gate audit-log reads behind `require_role(\"support_admin\")` (or higher) unless analyst "
      "access is an explicit product requirement.",
      ["Audit-log reads require support_admin or higher.",
       "Tests assert an analyst is denied audit-log reads."]),

    f(17, "daily-bonus-concurrent-500",
      "[BUG][MEDIUM] Concurrent daily-bonus claim raises 500 instead of AlreadyClaimed and poisons the session",
      "MEDIUM", "HIGH", 2, "complexity-low",
      ["bug", "tokens", "backend"], "backend",
      "A racing double-tap of the daily-bonus claim can trip the transactions unique index inside "
      "`token_service.add` (before the guarded claim insert), surfacing an unhandled 500 and "
      "aborting the session.",
      "`backend/app/services/daily_bonus.py:333-363` — the surrounding `try` only catches "
      "`UserNotFoundError`; `token_service.add` flushes a `Transaction` with a deterministic "
      "`payment_id` (`daily_bonus:user:{id}:date:...`) guarded by `uq_transactions_payment_id`. "
      "Only the later `DailyBonusClaim` insert is wrapped in `except IntegrityError`.",
      "No double-credit (the unique index prevents it — a correctness win) but a concurrent claim "
      "returns 500 instead of a clean `AlreadyClaimedError`, and the aborted transaction can break "
      "the rest of the request.",
      "Wrap the `token_service.add` call in `except IntegrityError` (rollback → "
      "`AlreadyClaimedError`) or use a `begin_nested()` savepoint, mirroring "
      "`payments._maybe_credit_referral_bonus`.",
      ["A concurrent second claim returns the clean AlreadyClaimed response, not 500.",
       "The session remains usable after the race.",
       "A concurrency test reproduces the race and asserts the fix."]),

    f(18, "writethrough-cache-uncommitted",
      "[BUG][MEDIUM] Write-through balance cache can serve uncommitted / rolled-back balances",
      "MEDIUM", "MEDIUM", 2, "complexity-medium",
      ["bug", "tokens", "backend"], "backend",
      "`spend`/`add`/`refund` write the new balance to Redis immediately after `flush()` but before "
      "the caller commits, so an outer rollback leaves a stale value cached until TTL.",
      "`backend/app/services/token_service.py:237-257` (`_refresh_cache`), called at `:317,394,531` "
      "right after `flush()` but before the request commits. `get_balance` serves that value.",
      "If the owning transaction later rolls back, Redis retains a value that was never committed "
      "(higher or lower than truth) until TTL, causing wrongful insufficient-tokens rejections or "
      "transient over-statement.",
      "Invalidate (delete) the cache key on mutation instead of writing pre-commit, or move the "
      "write-through to an after-commit hook so Redis only reflects committed state.",
      ["The cache never reflects an uncommitted/rolled-back balance.",
       "A test that rolls back after a spend asserts the cached balance matches the committed DB value."]),

    f(19, "toctou-generation-precheck",
      "[BUG][MEDIUM] TOCTOU pre-check in AI generation services burns provider cost under concurrency",
      "MEDIUM", "MEDIUM", 2, "complexity-medium",
      ["bug", "ai-service", "tokens", "backend"], "backend",
      "Flat-rate generation services check the balance with an unlocked cache-first read, then run "
      "the paid provider call, then debit with a locked `spend`; concurrent requests all pass the "
      "pre-check and incur real provider cost before the surplus debits fail.",
      "Identical pattern in `web_search.py:153→185`, `image_generation.py`, `text_generation.py`, "
      "`voice_processing.py`, `document_analysis.py`: `_assert_balance_sufficient` (unlocked "
      "`get_balance`) → provider call → `spend` (locked, refuses negative). Voice is worst (two "
      "provider calls for a flat 5-token charge).",
      "No negative balance and no free tokens to the user, but a user firing N parallel requests "
      "with balance for fewer than N forces several paid provider calls that then fail to debit — "
      "burnable upstream cost.",
      "Align flat-rate services with the video service's debit-first model (spend before invoking "
      "the provider, refund on provider failure), or treat `InsufficientTokensError` from `spend` "
      "as the only gate and drop reliance on the advisory pre-check.",
      ["Provider calls are not executed for requests that cannot be charged.",
       "A concurrency test confirms surplus parallel requests do not trigger provider calls."]),

    f(20, "broadcast-no-row-claiming",
      "[BUG][MEDIUM] Broadcast worker lacks row claiming → duplicate sends under overlapping runs",
      "MEDIUM", "HIGH", 2, "complexity-medium",
      ["bug", "telegram", "backend"], "backend",
      "Due broadcasts and pending recipients are selected without `FOR UPDATE SKIP LOCKED` or an "
      "atomic claim, so two overlapping passes (the documented 30s cron, `--loop`, or two replicas) "
      "send the same recipient twice.",
      "`backend/app/services/broadcast.py:534-558` (`list_due_broadcasts`) and `:561-577` "
      "(`fetch_pending_recipients`) select without locking; `mark_broadcast_started` flips status "
      "only after selection. `backend/app/workers/broadcast.py:72-89` drives the drain.",
      "The same recipient can receive a broadcast twice and the combined send rate exceeds the "
      "intended `rate_limit`, risking Telegram 429/flood bans. The README suggests a 30s cron, "
      "making overlap realistic for large campaigns.",
      "Claim recipients atomically (`UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED "
      "LIMIT n)`) or guard the whole drain with `SELECT ... FOR UPDATE SKIP LOCKED` on the "
      "Broadcast row so only one worker drains a campaign.",
      ["Overlapping worker passes never send a recipient twice.",
       "Concurrency test with two drains asserts exactly-once delivery per recipient."]),

    f(21, "webhook-update-id-idempotency",
      "[BUG][MEDIUM] No webhook `update_id` idempotency → double side effects on Telegram redelivery",
      "MEDIUM", "MEDIUM", 2, "complexity-medium",
      ["bug", "telegram", "backend"], "backend",
      "The webhook never records/checks `update_id`, so a Telegram redelivery (slow handler, pod "
      "restart, network error on the response) reprocesses the update and fires non-idempotent side "
      "effects again.",
      "`backend/app/api/v1/bot.py:94-114` logs but does not dedupe `update_id`; "
      "`dispatcher.py:45-92` reprocesses from scratch. `/bonus` and `successful_payment` are "
      "guarded, but `/start` referral crediting, `/image`/`/video`/`/ask` (token spend + provider "
      "cost) and broadcast click counting are not; the per-call `request_id` is fresh on redelivery.",
      "Redelivered updates can double-credit referrals, double-spend tokens and incur duplicate "
      "provider cost.",
      "Persist processed `update_id`s (Redis SETNX with TTL, or a unique table) and short-circuit "
      "duplicates before dispatch, returning 200 without re-running side effects.",
      ["A redelivered `update_id` is processed at most once.",
       "Test posts the same update twice and asserts side effects fire once."]),

    f(22, "broadcast-429-single-shot",
      "[BUG][MEDIUM] Broadcast 429 backoff is single-shot → drops recipients during sustained flood limit",
      "MEDIUM", "HIGH", 2, "complexity-low",
      ["bug", "telegram", "backend"], "backend",
      "On a 429 the drain waits once and retries a single time; if the retry also returns 429 the "
      "recipient is permanently marked FAILED and the loop continues without honouring the second "
      "`retry_after`.",
      "`backend/app/services/broadcast.py:800-827` — single retry after a 429, then "
      "`record_recipient_result(delivered=result.delivered)`; no global pause.",
      "During sustained flood limiting legitimate recipients are dropped as failed and the worker "
      "keeps hammering the API at `interval`, prolonging the penalty.",
      "Loop the backoff with bounded/exponential retries while `retry_after` is present; only mark "
      "FAILED after exhausting retries; consider pausing the whole drain on a 429.",
      ["A recipient hit by repeated 429s is retried with backoff, not immediately failed.",
       "The drain pauses globally on a 429 rather than only the current recipient.",
       "Test simulates repeated 429s and asserts no premature FAILED."]),

    f(23, "admin-open-redirect",
      "[SEC][MEDIUM] Admin dashboard open redirect via protocol-relative `from` parameter",
      "MEDIUM", "HIGH", 2, "complexity-low",
      ["bug", "security", "admin-crm"], "admin-dashboard",
      "The post-login redirect only checks `from.startsWith(\"/\")`, which accepts protocol-relative "
      "URLs like `//evil.com`, redirecting an authenticated admin off-site.",
      "`admin-dashboard/components/auth/login-form.tsx:86-88`\n"
      "```ts\nconst target = from && from.startsWith(\"/\") ? from : \"/dashboard\";\nrouter.replace(target);\n```\n"
      "`from` originates from `middleware.ts:37`.",
      "Phishing — after login the admin is silently sent to an attacker domain for credential/session "
      "harvesting on a lookalike page.",
      "Reject values starting with `//` (and backslash variants); accept only `/^\\/(?!\\/)/`, or "
      "parse with `new URL(from, origin)` and confirm same-origin.",
      ["`//evil.com` and `/\\evil.com` are rejected and fall back to `/dashboard`.",
       "Only same-origin relative paths are honoured (test)."]),

    f(24, "admin-middleware-role-gaps",
      "[SEC][MEDIUM] Admin middleware role map omits `/system` and `/content` (default to analyst)",
      "MEDIUM", "MEDIUM", 2, "complexity-low",
      ["bug", "security", "admin-crm"], "admin-dashboard",
      "The most privileged admin pages (`/system`, `/content`) are missing from the middleware role "
      "map and therefore only require `analyst`, inconsistent with the `super_admin` gate on "
      "`/pricing` and `/settings`.",
      "`admin-dashboard/middleware.ts:13-32` — `ROUTE_ROLES` lists `/pricing`, `/settings` "
      "(super_admin), `/broadcast`, `/users`, `/transactions` (support_admin) and defaults "
      "everything else to `analyst`. `/system` (manages admin users/roles, rate limits, maintenance, "
      "Composio) is not listed.",
      "A low-privilege analyst can load `/system` and trigger server-side reads of "
      "admin/role/rate-limit/Composio config; the front-end route-protection model is inconsistent "
      "and gives a false sense of gating.",
      "Add `{ prefix: \"/system\", required: \"super_admin\" }` and an appropriate entry for "
      "`/content`; keep the backend as the authoritative check.",
      ["`/system` requires super_admin and `/content` an appropriate role at the middleware layer.",
       "Tests assert an analyst is redirected away from `/system`."]),

    f(25, "admin-token-persist-no-validation",
      "[BUG][MEDIUM] Admin auth verify/refresh persist tokens without validating the upstream payload",
      "MEDIUM", "HIGH", 2, "complexity-low",
      ["bug", "admin-crm", "security"], "admin-dashboard",
      "On a 2xx upstream response with a missing/malformed body the verify/refresh routes write "
      "empty/garbage auth cookies and a session with no defined expiry.",
      "`admin-dashboard/app/api/auth/login/verify/route.ts:26-37` reads `payload.access_token` etc. "
      "without validation and calls `persistTokens` (`lib/auth/cookies.ts:22-35`) with possibly "
      "`undefined` values → `store.set(name, undefined, { maxAge: undefined })`. Same pattern in "
      "`app/api/auth/refresh/route.ts:24-29`.",
      "A malformed-but-2xx upstream reply yields broken cookies and an access cookie with no "
      "`maxAge`, causing confusing downstream verification failures.",
      "Validate the upstream payload with a zod schema (non-empty `access_token`/`refresh_token`, "
      "positive `expires_in`) before `persistTokens`; return 502 on mismatch.",
      ["Malformed upstream payloads return 502 and do not set cookies.",
       "Persisted cookies always have a defined value and maxAge.",
       "Tests cover the malformed-payload path."]),

    f(26, "miniapp-error-swallowing",
      "[BUG][MEDIUM] Mini App swallows API errors (no auth vs diagnostic distinction)",
      "MEDIUM", "HIGH", 2, "complexity-low",
      ["bug", "frontend"], "mini-app",
      "Profile/settings flows catch every error and show a generic string (or nothing), discarding "
      "status and message and never reporting to Sentry, so real auth failures look like empty data.",
      "`mini-app/src/pages/ProfilePage.tsx:41-49` sets `error = null` on 404; "
      "`mini-app/src/pages/SettingsPage.tsx:72-73,87-88` use bare `catch {}` with a generic message.",
      "Combined with the broken-routes finding, a permanently-404ing endpoint gives zero feedback "
      "and zero diagnostics; 401/403 auth failures are indistinguishable from \"no data\".",
      "Distinguish 401/403 from 404/5xx, surface a real message, and `Sentry.captureException` "
      "unexpected errors.",
      ["Auth errors are shown distinctly from missing data.",
       "Unexpected errors are reported to Sentry.",
       "Tests cover the 401/403 vs 404 branches."]),

    f(27, "miniapp-balance-not-refreshed",
      "[BUG][MEDIUM] Mini App chat never refreshes the displayed balance after token spend",
      "MEDIUM", "HIGH", 2, "complexity-low",
      ["bug", "frontend", "tokens"], "mini-app",
      "The backend returns the authoritative `new_balance` on chat/image/search/video responses, but "
      "the chat page never calls `setBalance`, so the displayed balance stays stale.",
      "`mini-app/src/services/chatApi.ts:30-37` exposes `new_balance`; `ChatPage.tsx` imports "
      "`useUserStore` but reads only `user` (`:33`) and `onFinal` updates only the message bubble "
      "(`:148-153`) — `setBalance` is never called.",
      "After spending tokens the user sees a too-high balance until the next Balance-page refetch, "
      "over-estimating remaining requests (server remains authoritative, so no over-spend).",
      "In `onFinal` (and the image/search/video success handlers) call "
      "`useUserStore.getState().setBalance(final.new_balance)` and/or invalidate the balance query.",
      ["The displayed balance updates immediately after a chat token spend.",
       "Test asserts `setBalance` is called with `new_balance` on `onFinal`."]),

    f(28, "alembic-autogenerate-partition-guard",
      "[DATA][MEDIUM] Alembic autogenerate lacks a partition guard → may emit destructive drops",
      "MEDIUM", "MEDIUM", 2, "complexity-low",
      ["bug", "database", "backend"], "backend",
      "`env.py` enables `compare_type`/`compare_server_default` but has no `include_object` filter, "
      "so autogenerate sees live partition child tables as unknown and would emit `drop_table` "
      "directives for the partitioned table.",
      "`backend/alembic/env.py:62-68` (and offline `:45-59`) — no `include_object`/`include_name` "
      "and no `process_revision_directives`. SQLAlchemy autogenerate doesn't understand "
      "`postgresql_partition_by` or `token_usage_logs_YYYY_MM` children.",
      "A future `--autogenerate` may produce `op.drop_table(\"token_usage_logs_2026_05\")` and "
      "re-create directives, risking data loss if applied blindly.",
      "Add an `include_object`/`include_name` callback that skips partition child tables and the "
      "partitioned parent.",
      ["`--autogenerate` ignores partition-managed objects.",
       "A test or documented check confirms no spurious drop directives for partitions."]),

    f(29, "secret-scan-gaps",
      "[DEVOPS][MEDIUM] Secret-scan gaps: over-broad gitleaks allowlist + `npm audit --audit-level=critical`",
      "MEDIUM", "HIGH", 2, "complexity-low",
      ["bug", "devops", "security"], "devops",
      "The gitleaks config disables secret scanning across all Markdown and globally allowlists "
      "`change-me`/`CHANGEME`, and the npm-audit CI gate only fails on Critical, so HIGH JS "
      "advisories merge unblocked.",
      "`.gitleaks.toml:18-48` — `paths` includes `(^|/).+\\.md$` (every `.md`) and globally "
      "allowlists `change-me`/`CHANGEME`. `.github/workflows/security.yml:99-108` runs "
      "`npm audit --omit=dev --audit-level=critical`.",
      "A real secret pasted into any `.md` (runbook, incident note) is invisible to the scanner, "
      "and new HIGH-severity dependency CVEs can land on `main` without blocking.",
      "Narrow the gitleaks path allowlist to specific fixture dirs (e.g. `docs/**` only where "
      "needed) and scope the `change-me` allowlist to known placeholder lines; restore "
      "`--audit-level=high` with a short, time-boxed, individually-justified exceptions list.",
      ["Secret scanning covers Markdown outside an explicit narrow allowlist.",
       "`npm audit` fails on new HIGH advisories.",
       "Existing placeholder lines are allowlisted narrowly, not globally."]),

    f(30, "monitoring-default-creds",
      "[DEVOPS][MEDIUM] Monitoring stack ships Grafana `admin/admin` and unauthenticated Prometheus/Alertmanager/Loki",
      "MEDIUM", "MEDIUM", 2, "complexity-low",
      ["bug", "devops", "security", "analytics"], "devops",
      "The optional monitoring compose stack uses default Grafana credentials and publishes "
      "Prometheus/Alertmanager/Loki on host ports with no auth.",
      "`deploy/monitoring/docker-compose.monitoring.yml:24-66` — "
      "`GF_SECURITY_ADMIN_USER/PASSWORD: admin` (`:45-46`) and host-published `9090/9093/3000/3100` "
      "with no auth proxy; Prometheus runs `--web.enable-lifecycle`.",
      "If ever run on a non-loopback host, Grafana is takeover-able with default creds and "
      "Prometheus/Alertmanager/Loki are fully open (config reload/shutdown, alert silencing, "
      "metrics/log exposure).",
      "Parameterise the Grafana admin password (`${GF_SECURITY_ADMIN_PASSWORD:?}`), bind published "
      "ports to `127.0.0.1`, and document that this stack must not be exposed publicly.",
      ["Grafana admin password is required via env (no `admin/admin` default).",
       "Monitoring ports bind to loopback by default.",
       "Docs warn against public exposure."]),

    # ===================== LOW / Stage 3 =====================
    f(31, "auth-hardening-bundle",
      "[SEC][LOW] Auth hardening: non-constant-time webhook compare, TOTP replay window, admin enumeration",
      "LOW", "MEDIUM", 3, "complexity-low",
      ["bug", "security", "backend"], "backend",
      "Three low-severity auth hardening items: a non-constant-time webhook-secret comparison, a "
      "replayable TOTP window, and admin enumeration via distinct login responses.",
      "(1) `backend/app/api/v1/bot.py:68-75` uses `received != expected` instead of "
      "`hmac.compare_digest`. (2) `backend/app/auth/totp.py:23-44` accepts a code for the current "
      "step ±1 with no used-code tracking (enforced at `auth.py:239-249`) — replayable for ~90s. "
      "(3) `backend/app/api/v1/auth.py:151-165` (`_require_admin_candidate`) returns "
      "`403 not_an_admin` for non-admins but proceeds for admins, enabling admin-ID enumeration.",
      "Individually minor: a theoretical timing oracle on the webhook secret, a ~90s TOTP replay "
      "window, and admin-ID enumeration that aids targeted brute force.",
      "(1) Use `hmac.compare_digest`. (2) Persist the last accepted TOTP timestep per super-admin "
      "and reject `<=` it. (3) Return a uniform generic response for admin and non-admin IDs on the "
      "login `request` endpoint.",
      ["Webhook secret compared in constant time.",
       "A TOTP code cannot be reused within its window.",
       "The admin-login request response does not reveal admin status."]),

    f(32, "admin-role-headers-leak",
      "[SEC][LOW] Admin middleware leaks `x-admin-role` / `x-admin-sub` response headers",
      "LOW", "MEDIUM", 3, "complexity-low",
      ["bug", "security", "admin-crm"], "admin-dashboard",
      "The middleware sets `x-admin-role` and `x-admin-sub` on the response to the browser, leaking "
      "the admin's privilege level and id on every protected response for no functional benefit.",
      "`admin-dashboard/middleware.ts:63-66` — `response.headers.set(\"x-admin-role\", payload.role)` "
      "and `set(\"x-admin-sub\", payload.sub)`; no server code reads them.",
      "Minor information disclosure of the authenticated admin's id and privilege on every response, "
      "visible in dev tools / intermediaries.",
      "Remove these `response.headers.set(...)` lines. If downstream identity propagation is needed, "
      "set them on the forwarded request headers and never trust inbound `x-admin-*`.",
      ["Protected responses no longer carry `x-admin-role`/`x-admin-sub`.",
       "Identity propagation (if any) uses request headers only."]),

    f(33, "db-index-hygiene",
      "[DATA][LOW] Redundant indexes on `users.telegram_id`/`referral_code`; `usage_log_id` has no FK",
      "LOW", "HIGH", 3, "complexity-low",
      ["bug", "database", "backend"], "backend",
      "Two single-column duplicate B-tree indexes on a hot table waste storage and add write "
      "amplification; `usage_log_id` columns carry no FK (an unavoidable consequence of the "
      "composite partitioned PK, worth documenting).",
      "`backend/app/models/user.py:20,58,80,86` — `telegram_id`/`referral_code` are `unique=True` "
      "(unique index) *and* get extra `Index(\"ix_users_telegram_id\", ...)` / `ix_users_referral`. "
      "`chat_history.py:121`, `video_job.py:84` reference `token_usage_logs` with no FK (the "
      "composite PK `(id, created_at)` makes a single-column FK impossible).",
      "Wasted storage / write amplification on `users`; no referential integrity on `usage_log_id` "
      "links (dangling on rotation).",
      "Drop the redundant `ix_users_telegram_id`/`ix_users_referral` indexes (keep the unique ones) "
      "via a migration; either accept and document the FK-less link or store "
      "`(usage_log_id, usage_log_created_at)` with a composite FK.",
      ["Redundant single-column indexes are removed (model + migration).",
       "The `usage_log_id` FK decision is documented or implemented."]),

    f(34, "miniapp-frontend-hygiene",
      "[FRONT][LOW] Mini App retries 4xx requests and ships source maps to production",
      "LOW", "MEDIUM", 3, "complexity-low",
      ["bug", "frontend"], "mini-app",
      "The global query client retries all failures once (including auth/4xx), and the production "
      "build emits public source maps.",
      "`mini-app/src/services/queryClient.ts:18` sets `retry: 1` with no predicate (balance, "
      "packages, transactions, referral all use it). `mini-app/vite.config.ts` sets "
      "`build.sourcemap: true`.",
      "Pointless retries double latency/load on auth-rejecting endpoints; full original TypeScript "
      "is published alongside the bundle (no secrets are exposed, so impact is source disclosure).",
      "Use a `retry` predicate that returns `false` for 4xx and retries only network/5xx; set "
      "`sourcemap: false` (or `\"hidden\"` + upload to Sentry only) for production builds.",
      ["4xx responses are not retried.",
       "Production builds do not publish public source maps."]),

    f(35, "ci-supply-chain",
      "[DEVOPS][LOW] CI supply-chain: third-party actions pinned to mutable tags; kubeval `continue-on-error`",
      "LOW", "HIGH", 3, "complexity-low",
      ["bug", "devops", "security"], "devops",
      "Workflows pin third-party actions to mutable major-version tags (and "
      "`instrumenta/kubeval-action@master`), and the only K8s-manifest validation step is "
      "`continue-on-error`, so it is effectively decorative.",
      "`.github/workflows/*.yml` reference `@v6`/`@v2`/`@v0.36.0` and "
      "`instrumenta/kubeval-action@master` (`ci.yml:125`); privileged jobs run with "
      "`packages: write`/`security-events: write`/`contents: write`. `ci.yml:124-128` sets "
      "`continue-on-error: true` on the kubeval step.",
      "A compromised/retagged action (especially the unpinned `@master` from an unmaintained "
      "third party) executes in CI with write scopes; invalid manifests never fail CI and can reach "
      "`helm upgrade`.",
      "Pin third-party actions to a full commit SHA (especially `kubeval-action`); switch to a "
      "maintained, pinned validator (kubeconform) and remove `continue-on-error`.",
      ["Third-party actions are SHA-pinned.",
       "Manifest validation fails CI on invalid manifests."]),
]


def render_body(x: Finding) -> str:
    acc = "\n".join(f"- [ ] {a}" for a in x["acceptance"])
    return f"""## Summary

{x['summary']}

| | |
|---|---|
| **Severity** | {x['severity']} |
| **Confidence** | {x['confidence']} |
| **Area** | {x['area']} |
| **Remediation stage** | {STAGES[x['stage']]} |
| **Estimated complexity** | {x['complexity'].replace('complexity-', '').title()} |

## Evidence

{x['evidence']}

## Impact

{x['impact']}

## Suggested fix

{x['fix']}

## Acceptance criteria

{acc}

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
"""


def main() -> None:
    FIND.mkdir(parents=True, exist_ok=True)
    manifest = []
    for x in FINDINGS:
        fname = f"{x['num']:02d}-{x['slug']}.md"
        (FIND / fname).write_text(render_body(x), encoding="utf-8")
        manifest.append({
            "num": x["num"], "file": f"docs/audit/findings/{fname}",
            "title": x["title"], "labels": x["labels"],
            "severity": x["severity"], "stage": x["stage"],
        })

    # Master index / report
    rows = []
    for x in sorted(FINDINGS, key=lambda y: (y["stage"], y["num"])):
        sev = x["severity"]
        rows.append(
            f"| #{x['num']:02d} | {x['title'].split('] ',1)[-1]} | {sev} | "
            f"`{x['area']}` | Stage {x['stage']} | "
            f"[body](findings/{x['num']:02d}-{x['slug']}.md) |"
        )
    by_sev = {}
    for x in FINDINGS:
        by_sev[x["severity"]] = by_sev.get(x["severity"], 0) + 1
    sev_line = ", ".join(
        f"**{k}**: {by_sev.get(k,0)}" for k in ("CRITICAL", "HIGH", "MEDIUM", "LOW"))

    index = f"""# Code Audit — Issue #136

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

Total findings: **{len(FINDINGS)}** — {sev_line}.

The highest-impact issues are cross-corroborated and re-verified against the
source (e.g. `request.state.user` is never set → rate limiting collapses to a
spoofable anonymous bucket; the admin dashboard signs JWTs with a committed
`change-me` fallback; `token_usage_logs` runs out of partitions ~2 months after
deploy).

| # | Finding | Severity | Area | Stage | Detail |
|---|---------|----------|------|-------|--------|
{chr(10).join(rows)}

## Remediation stages

- **{STAGES[0]}** — deploy-blocking; forgeable admin auth and a table that stops
  accepting inserts in production.
- **{STAGES[1]}** — security and data-integrity defects that should be fixed next.
- **{STAGES[2]}** — correctness and hardening defects.
- **{STAGES[3]}** — hygiene and defence-in-depth.

## Methodology

Each subsystem was audited independently (auth/security, HTTP API, services &
billing, bot & workers, data/migrations, Mini App, admin dashboard, devops). Only
findings at MEDIUM+ confidence are reported; the highest-severity ones were
re-verified by reading the cited source. Each finding records exact `file:line`
evidence, concrete impact, a suggested fix and acceptance criteria.

See the individual files in [`findings/`](findings/) for full write-ups; each maps
1:1 to a GitHub issue.
"""
    (OUT / "README.md").write_text(index, encoding="utf-8")

    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
