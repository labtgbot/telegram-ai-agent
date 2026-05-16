# Production Deploy Runbook — v1.0.0

Step-by-step runbook for cutting the **first** public release of the
Telegram AI Agent. This document is the cutover script that the
release manager follows on launch day; it is **not** a substitute for
[`docs/DEPLOYMENT.md`](DEPLOYMENT.md), which covers the steady-state
deployment surface (Helm values, secrets, canary controls).

Read in tandem with:

- [`docs/LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md) — acceptance gates.
- [`docs/DEPLOYMENT.md`](DEPLOYMENT.md) — environment & Helm reference.
- [`docs/MONITORING.md`](MONITORING.md) — alert rules and dashboards.
- [`docs/POST_LAUNCH.md`](POST_LAUNCH.md) — the 72-hour watch that
  starts the moment this runbook ends.

---

## 0. Roles

| Role             | Responsibility                                          |
|------------------|---------------------------------------------------------|
| Release manager  | Drives this runbook, owns the go/no-go decision.        |
| Primary on-call  | Watches Grafana + Sentry, executes rollback if asked.   |
| Comms lead       | Posts the announcement after the smoke test passes.     |
| Database owner   | Available for an emergency migration revert.            |

Block out a **two-hour** window. Production deploy itself takes 15–30
minutes; the rest is the smoke test, BotFather flip and the first
monitoring soak. Schedule outside peak user hours (avoid 17:00–22:00
UTC).

---

## 1. Pre-flight gates (T-24h)

All gates must be green before the tag is pushed. Each maps to a
section in [`LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md).

| Gate                                            | Evidence                                                         |
|-------------------------------------------------|------------------------------------------------------------------|
| `main` is green on CI                           | `gh run list --branch main --limit 5` — all `success`.           |
| Latest staging deploy is healthy                | Grafana → `staging` folder, `SLO` dashboard all green for 24 h.  |
| Backups verified within the last 24 h           | `kubectl -n tgai-prod get cronjob backup-verify` last success.   |
| Restore drill performed this quarter            | Linked from `docs/BACKUP_RECOVERY.md` exec log.                  |
| Load test passed                                | `loadtest/results/*-launch-100u.json` archived in this PR.       |
| Beta program report signed off                  | `docs/templates/BETA_REPORT.template.md` filled in this PR.      |
| `docs/CHANGELOG.md` Unreleased moved to v1.0.0  | Diff in the release PR.                                          |
| Helm `values-production.yaml` reviewed          | Required image tag, replica counts, HPA limits.                  |
| Secrets present in production namespace        | `kubectl -n tgai-prod get secret telegram-ai-agent-backend`.    |
| Feature flags pinned                            | `PAYMENTS_TON_ENABLED=false`, `PAYMENTS_STRIPE_ENABLED=false`.   |

If any gate is red, **abort the cutover** and re-schedule. Do not
launch with a workaround.

---

## 2. Cut the release (T-30m)

The repo is configured so the release artefacts are produced by a Git
tag — the human action is one push.

```bash
# 2.1 Move the Unreleased block to v1.0.0 in docs/CHANGELOG.md and
#     commit it on main:
git switch main
git pull --ff-only
$EDITOR docs/CHANGELOG.md
git add docs/CHANGELOG.md
git commit -m "docs(changelog): release v1.0.0"
git push origin main

# 2.2 Tag and push. The `Release` workflow takes it from here.
git tag -a v1.0.0 -m "Telegram AI Agent v1.0.0"
git push origin v1.0.0
```

Verify the [`Release`](../.github/workflows/release.yml) workflow:

```bash
gh run watch --exit-status \
  $(gh run list --workflow=release.yml --branch=v1.0.0 \
      --limit 1 --json databaseId --jq '.[0].databaseId')
```

Expected artefacts:

- GHCR images tagged `1.0.0`:
  - `ghcr.io/labtgbot/telegram-ai-agent-backend:1.0.0`
  - `ghcr.io/labtgbot/telegram-ai-agent-miniapp:1.0.0`
  - `ghcr.io/labtgbot/telegram-ai-agent-admin:1.0.0`
- A GitHub Release at `v1.0.0` with the matching CHANGELOG section as
  the body (empty body → release-notes section was left blank, abort).

---

## 3. Database migration dry-run (T-15m)

Even though Alembic migrations are additive for v1.0.0, run the dry-run
against a fresh restore of the production snapshot. The drill catches
schema drift between staging and production.

```bash
# Spin a one-off pod from the new image, against a restored snapshot
# (see docs/BACKUP_RECOVERY.md §"Restore drill"):
kubectl -n tgai-prod-restore run alembic-dryrun \
  --image=ghcr.io/labtgbot/telegram-ai-agent-backend:1.0.0 \
  --restart=Never --rm -i --tty \
  --env="DATABASE_URL=$RESTORE_DATABASE_URL" \
  -- alembic upgrade head --sql > /tmp/alembic-1.0.0.sql

# Review the generated SQL:
wc -l /tmp/alembic-1.0.0.sql
grep -E '^(ALTER|DROP|CREATE)' /tmp/alembic-1.0.0.sql
```

Any `DROP TABLE`, `DROP COLUMN`, or non-additive `ALTER` is a blocker.
For destructive schema changes, ship a two-step deploy per
[`docs/DEPLOYMENT.md`](DEPLOYMENT.md) §5.

---

## 4. The cutover (T-0)

### 4.1 Promote the deploy

```bash
helm upgrade telegram-ai-agent deploy/helm/telegram-ai-agent \
  --namespace tgai-prod \
  -f deploy/helm/telegram-ai-agent/values.yaml \
  -f deploy/helm/telegram-ai-agent/values-production.yaml \
  --set image.tag=1.0.0 \
  --atomic --wait --timeout 10m
```

`--atomic` rolls the release back automatically if the wait times out.

### 4.2 Watch the canary

`values-production.yaml` ships `backend.rollout.enabled=true` with
canary steps `10 → 30 → 60 → 100 %`. Each step pauses for a manual
promotion — that is intentional.

```bash
kubectl argo rollouts get rollout telegram-ai-agent-backend \
  -n tgai-prod -w
```

Promote a step only after **all** of the following are true for the
preceding 5 minutes:

- `BackendAvailabilityFastBurn` not firing
  ([`MONITORING.md`](MONITORING.md) §SLO alerts).
- `BackendReadLatencyP95High` not firing.
- No new Sentry issues with `level=error` from the new release.
- `payment_events_total{event="successful_payment"}` is non-decreasing
  in the Business dashboard.

Promote with:

```bash
kubectl argo rollouts promote telegram-ai-agent-backend -n tgai-prod
```

If any of the four signals breaks, **abort** before the next step:

```bash
kubectl argo rollouts abort telegram-ai-agent-backend -n tgai-prod
```

### 4.3 Run the migration

After 100 % of pods are on `1.0.0`:

```bash
kubectl -n tgai-prod exec deploy/telegram-ai-agent-backend -- \
  alembic upgrade head
```

The migration runner uses the same `DATABASE_URL` env as the API; if it
exits non-zero, rollback per §6 below.

### 4.4 Apply BotFather configuration

```bash
TELEGRAM_BOT_TOKEN=$(op read 'op://prod/telegram-bot-token/password') \
TELEGRAM_BOT_USERNAME=telegram_ai_agent_bot \
TELEGRAM_MINI_APP_URL=https://app.telegram-ai-agent.example.com \
  python -m scripts.configure_botfather
```

The script is idempotent — re-running on partial failure picks up
where it left off. Dry-run first (`TELEGRAM_BOTFATHER_DRY_RUN=1`) if
the previous run crashed mid-flight.

### 4.5 Stars smoke test

```bash
SMOKE_BASE_URL=https://api.telegram-ai-agent.example.com \
SMOKE_AUTH_TOKEN="$RELEASE_MANAGER_INIT_DATA" \
SMOKE_PACKAGE_CODE=starter \
  python -m scripts.launch_smoketest
```

The script must exit `0` with `payment_id` prefixed `tg:` for the
completed transaction. Archive the JSON output in the launch ticket.

---

## 5. Post-deploy verification (T+15m)

Run the full verification surface before handing off to comms.

```bash
# 5.1 Backend liveness + readiness
curl -fsS https://api.telegram-ai-agent.example.com/api/v1/health/live
curl -fsS https://api.telegram-ai-agent.example.com/api/v1/health | jq

# 5.2 Mini App reaches the API
curl -fsSI https://app.telegram-ai-agent.example.com/ \
  | grep -E '^(HTTP|content-security-policy)'

# 5.3 Admin login screen renders
curl -fsSI https://admin.telegram-ai-agent.example.com/login \
  | grep -E '^HTTP'

# 5.4 Webhook secret is in place
curl -fsS \
  "https://api.telegram.org/bot$BOT_TOKEN/getWebhookInfo" \
  | jq '.result.url, .result.has_custom_certificate, .result.pending_update_count'
```

Expected output:

- `/health` JSON has `database.status=ok` and `redis.status=ok`.
- Webhook URL points at
  `https://api.telegram-ai-agent.example.com/api/v1/bot/webhook`.
- `pending_update_count` is `0` after the smoke transaction.

Then verify Grafana:

- **Business** dashboard shows the smoke-test transaction.
- **SLO** dashboard read p95 < 500 ms, write p95 < 2 s.
- **Infra** dashboard: backend pods at desired replicas, HPA stable.

---

## 6. Rollback

Trigger rollback if **any** of the following hits during the canary or
the first hour after promotion:

| Trigger                                            | Action                                                                |
|----------------------------------------------------|-----------------------------------------------------------------------|
| `BackendAvailabilityFastBurn` fires for 5 min      | `kubectl argo rollouts abort telegram-ai-agent-backend -n tgai-prod`  |
| 5xx ratio > 5 % for 5 min on the new revision      | `helm rollback telegram-ai-agent -n tgai-prod --wait`                 |
| Payment success rate drops below 95 %              | Rollback + freeze `setMyCommands` revert (re-run BotFather script).   |
| Alembic migration fails                            | Stop. Page the database owner. Plan a forward-fix migration.          |
| Wide Sentry spike (new issue, >50 events / minute) | Rollback + open incident channel.                                     |

Rollback commands:

```bash
# Roll forward-revert if the new release is in flight:
kubectl argo rollouts abort telegram-ai-agent-backend -n tgai-prod
kubectl argo rollouts undo  telegram-ai-agent-backend -n tgai-prod

# Hard rollback once the bad release is fully live:
helm rollback telegram-ai-agent -n tgai-prod --wait --timeout 10m
helm history  telegram-ai-agent -n tgai-prod   # confirm REVISION

# If migrations have to revert, run the reverse Alembic step from the
# previous image:
kubectl -n tgai-prod set image deploy/telegram-ai-agent-backend \
  backend=ghcr.io/labtgbot/telegram-ai-agent-backend:<previous-tag>
kubectl -n tgai-prod exec deploy/telegram-ai-agent-backend -- \
  alembic downgrade -1
```

After the rollback, post an incident in the release ticket with:

- The trigger (which alert, which signal).
- Image tag that was rolled back from / to.
- Timestamps for rollback start / end.
- Whether a forward fix or a new tag is required.

---

## 7. Hand-off (T+1h)

Once the smoke test, the verification and the first hour of soaking
are clean:

1. Comms lead publishes the announcement from
   [`docs/marketing/announcement-en.md`](marketing/announcement-en.md)
   and the Russian counterpart.
2. Release manager opens the post-launch watch ticket per
   [`docs/POST_LAUNCH.md`](POST_LAUNCH.md).
3. Primary on-call confirms the 72-hour watch schedule in the on-call
   chat.

The cutover is complete when the watch ticket is open and the on-call
acknowledges it.
