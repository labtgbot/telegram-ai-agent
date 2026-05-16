# Deployment Runbook

Production-grade deployment guide for **Telegram AI Agent**. Two supported
targets:

1. **Kubernetes** (recommended) via the Helm chart in
   [`deploy/helm/telegram-ai-agent`](../deploy/helm/telegram-ai-agent).
2. **Single-host Docker Compose** via
   [`docker/compose.prod.yml`](../docker/compose.prod.yml) — a fallback for
   small / staging deployments where K8s is overkill.

For local development see [`README.md`](../README.md) — this document covers
staging + production only.

---

## 1. Environments

| Env        | URL pattern                                             | Database          | Strategy             |
|------------|---------------------------------------------------------|-------------------|----------------------|
| local      | `http://localhost:8000`                                 | docker postgres   | dev only             |
| staging    | `https://staging-bot.example.com` / `staging-admin.…`   | managed PG (small)| auto on release tag  |
| production | `https://bot.example.com` / `admin.example.com`         | managed PG (HA)   | manual-approved      |

Per-environment values:

- `deploy/helm/telegram-ai-agent/values.yaml` — defaults
- `deploy/helm/telegram-ai-agent/values-staging.yaml` — staging overrides
- `deploy/helm/telegram-ai-agent/values-production.yaml` — production overrides

---

## 2. Prerequisites

### Cluster

- Kubernetes ≥ 1.27
- An ingress controller (`ingress-nginx` assumed; the chart's
  `ingress.className` defaults to `nginx`)
- Persistent volumes for managed Postgres (or external managed Postgres)

### Cluster add-ons

| Component               | Purpose                            | Manifest                              |
|-------------------------|------------------------------------|---------------------------------------|
| cert-manager            | ACME TLS certificates              | `deploy/k8s/cert-manager/*.yaml`      |
| sealed-secrets *or*     | Secret material checked in to git  | `deploy/k8s/secrets/sealed-secret.example.yaml` |
| external-secrets        | Pull secrets from AWS / Vault / …  | `deploy/k8s/secrets/{external-secret,secret-store}.example.yaml` |
| argo-rollouts (optional)| Canary / blue-green for backend    | `deploy/k8s/rollouts/README.md`       |

Install once per cluster — see the relevant project's docs.

### Workstation

- `kubectl` ≥ 1.27
- `helm` ≥ 3.16
- `kubeseal` (if using sealed-secrets) or AWS / Vault CLI (external-secrets)
- `kubectl-argo-rollouts` (optional, for canary monitoring)

---

## 3. One-time bootstrap per environment

### 3.1 Create the namespace

```bash
kubectl create namespace tgai-staging
# or:
kubectl create namespace tgai-prod
```

### 3.2 Install ClusterIssuers (cert-manager)

```bash
kubectl apply -f deploy/k8s/cert-manager/cluster-issuer-staging.yaml
kubectl apply -f deploy/k8s/cert-manager/cluster-issuer-prod.yaml
```

`values-staging.yaml` references `letsencrypt-staging`,
`values-production.yaml` references `letsencrypt-prod`.

### 3.3 Provision secrets

The chart **never** generates production secrets. Pick one path:

**Path A — sealed-secrets (gitops-friendly):**

```bash
# Encrypt locally and commit the SealedSecret manifest:
kubectl -n tgai-prod create secret generic telegram-ai-agent-backend \
  --from-literal=BOT_TOKEN=… \
  --from-literal=SECRET_KEY=… \
  --from-literal=POSTGRES_PASSWORD=… \
  --dry-run=client -o yaml \
  | kubeseal --controller-namespace=kube-system -o yaml \
  > sealed-telegram-ai-agent-backend.yaml

kubectl apply -f sealed-telegram-ai-agent-backend.yaml
```

See `deploy/k8s/secrets/sealed-secret.example.yaml` for the expected shape.

**Path B — external-secrets-operator (recommended for managed clouds):**

```bash
# 1. Wire ClusterSecretStore (one-time per cluster):
kubectl apply -f deploy/k8s/secrets/secret-store.example.yaml
# 2. Reference your provider entries via ExternalSecret:
kubectl apply -f deploy/k8s/secrets/external-secret.example.yaml
```

Both paths produce a `Secret` named **`telegram-ai-agent-backend`** matching
`backend.envFrom[].secretRef.name` in `values.yaml`.

Required keys (also documented in `.env.example`): `BOT_TOKEN`,
`TELEGRAM_WEBHOOK_SECRET`, `SECRET_KEY`, `POSTGRES_PASSWORD`,
`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `COMPOSIO_API_KEY`.

### 3.4 (Optional) Pre-create blue/green preview Service

If you flip `backend.rollout.strategy` to `blueGreen`, apply the preview
service once per env:

```bash
kubectl apply -f deploy/k8s/rollouts/backend-preview-service.example.yaml
```

### 3.5 DNS

Point `A`/`AAAA` records for `bot.example.com` and `admin.example.com` at the
ingress controller's external IP **before** the first deploy — Let's Encrypt
`HTTP-01` solver needs the hostname to resolve.

---

## 4. Deploying

### 4.1 Staging (automated)

A push of a `vX.Y.Z` tag triggers `.github/workflows/release.yml`, which:

1. Cuts a GitHub Release with auto-generated notes.
2. Runs `helm lint` + `helm template` against `values-staging.yaml`.
3. Calls `helm upgrade --install` if `STAGING_KUBECONFIG` secret is set;
   otherwise hits `STAGING_DEPLOY_HOOK` if configured.

Required GitHub secrets/vars for staging:

| Name                  | Type   | Notes                                          |
|-----------------------|--------|------------------------------------------------|
| `STAGING_KUBECONFIG`  | secret | base64-encoded kubeconfig with `helm` access   |
| `STAGING_NAMESPACE`   | var    | optional; defaults to `tgai-staging`           |
| `STAGING_URL`         | var    | shown in the GitHub Environment banner         |

To deploy by hand:

```bash
helm upgrade --install telegram-ai-agent deploy/helm/telegram-ai-agent \
  --namespace tgai-staging --create-namespace \
  -f deploy/helm/telegram-ai-agent/values.yaml \
  -f deploy/helm/telegram-ai-agent/values-staging.yaml \
  --set image.tag=$(git describe --tags --abbrev=0 | sed 's/^v//') \
  --wait --timeout 5m
```

### 4.2 Production (manual approval)

The `deploy-production` job in `release.yml` uses the GitHub `production`
environment. Configure it under **Settings → Environments → production**:

- **Required reviewers**: ops / release-managers team.
- Optional: wait timer, deployment branches (`main` only).

Once a release tag's `deploy-staging` succeeds the production job sits
awaiting approval. Approvers see image refs and the rendered Helm template
in the job summary before clicking _Approve_.

Same secrets/vars as staging, prefixed `PRODUCTION_`:

| Name                       | Type   | Notes                                  |
|----------------------------|--------|----------------------------------------|
| `PRODUCTION_KUBECONFIG`    | secret | base64-encoded kubeconfig             |
| `PRODUCTION_NAMESPACE`     | var    | optional; defaults to `tgai-prod`     |
| `PRODUCTION_URL`           | var    | shown in the Environment banner       |

Manual production deploy (break-glass):

```bash
helm upgrade --install telegram-ai-agent deploy/helm/telegram-ai-agent \
  --namespace tgai-prod --create-namespace \
  -f deploy/helm/telegram-ai-agent/values.yaml \
  -f deploy/helm/telegram-ai-agent/values-production.yaml \
  --set image.tag=$VERSION \
  --wait --timeout 10m
```

### 4.3 Canary (production)

`values-production.yaml` already enables `backend.rollout.enabled=true` with
canary steps `10 → 30 → 60 → 100`% and pauses between each step. The chart
swaps the standard Deployment for an `argoproj.io/v1alpha1` Rollout so
**install argo-rollouts in the cluster first** (see
`deploy/k8s/rollouts/README.md`).

Watch and gate promotion:

```bash
kubectl argo rollouts get rollout telegram-ai-agent-backend -n tgai-prod -w
kubectl argo rollouts promote telegram-ai-agent-backend -n tgai-prod
# or, on smoke-check failure:
kubectl argo rollouts abort telegram-ai-agent-backend -n tgai-prod
```

To roll back to the previous good version:

```bash
kubectl argo rollouts undo telegram-ai-agent-backend -n tgai-prod
```

---

## 5. Database migrations

The chart does not run migrations automatically. Apply them after the helm
upgrade lands (during canary, run before promoting the second step):

```bash
kubectl -n tgai-prod exec deploy/telegram-ai-agent-backend -- \
  alembic upgrade head
```

For schema changes that aren't backward-compatible with the previous image
tag, use a two-step deploy:

1. Ship a release containing only the additive migration. Run it.
2. Ship the release that uses the new column / table.

---

## 6. Smoke checks

After each promotion step:

```bash
# liveness
curl -sf https://bot.example.com/api/v1/health/live

# readiness (DB + Redis)
curl -sf https://bot.example.com/api/v1/health | jq

# webhook resolves through ingress
curl -sI https://bot.example.com/api/v1/bot/webhook

# admin loads
curl -sI https://admin.example.com/
```

All four should return `2xx`. The `/api/v1/health` payload must show
`"status": "ok"` for both `database` and `redis` checks.

If staging changes the bot username or token, **re-register the webhook**:

```bash
curl -X POST https://api.telegram.org/bot<TOKEN>/setWebhook \
  -d "url=https://bot.example.com/api/v1/bot/webhook" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```

---

## 7. Rollback

| Scenario                          | Command                                                        |
|-----------------------------------|----------------------------------------------------------------|
| Canary in flight, bad signal      | `kubectl argo rollouts abort telegram-ai-agent-backend -n tgai-prod` |
| Latest revision live, want prior  | `helm rollback telegram-ai-agent -n tgai-prod`                |
| Rollback to a specific revision   | `helm rollback telegram-ai-agent <REV> -n tgai-prod`           |
| Migration must also revert        | Run the reverse migration in a hotfix release before rollback. |

`helm history telegram-ai-agent -n tgai-prod` lists revisions.

---

## 8. Docker Compose fallback

For single-host shells (staging without a cluster, on-prem boxes):

```bash
cp .env.example .env.prod
$EDITOR .env.prod                # fill secrets, DOMAIN, ADMIN_DOMAIN, ACME_EMAIL
docker compose -f docker/compose.prod.yml --env-file .env.prod pull
docker compose -f docker/compose.prod.yml --env-file .env.prod up -d
docker compose -f docker/compose.prod.yml exec backend alembic upgrade head
```

`docker/Caddyfile.prod` terminates TLS via Caddy's built-in ACME client.
Point `bot.example.com` + `admin.example.com` at the host before bringing
the stack up.

---

## 9. CI/CD summary

| Workflow                       | Trigger                          | Purpose                                  |
|--------------------------------|----------------------------------|------------------------------------------|
| `.github/workflows/ci.yml`     | PR, push to `main`               | Lint + test (backend, mini-app, admin)   |
| `.github/workflows/build.yml`  | push to `main`, tag              | Build + push images to GHCR              |
| `.github/workflows/deploy.yml` | changes under `deploy/` or compose | Lint Helm chart + parse compose file    |
| `.github/workflows/release.yml`| `v*.*.*` tag, workflow_dispatch  | GH release → deploy staging → deploy prod (manual approval) |

Release tags follow `vMAJOR.MINOR.PATCH`. Pre-releases (`v1.2.0-rc.1`) flip
`prerelease: true` in the GitHub Release automatically.

---

## 10. Monitoring & backups

### 10.1 Monitoring

- **Metrics**: scrape `/api/v1/health` and per-pod cAdvisor metrics with
  Prometheus; dashboards live in `deploy/observability/` (TBD).
- **Errors**: Sentry DSN injected via the backend Secret.
- **Logs**: structured JSON to stdout; ship with `fluent-bit` / vendor agent.
- **Alerts**: route critical alerts to the on-call Telegram chat.

### 10.2 Disaster recovery (DR)

The complete DR runbook — bucket provisioning, WAL archiving, restore drills,
scenario-by-scenario recovery procedures, RPO/RTO budgets and the quarterly
verification schedule — lives in [`docs/BACKUP_RECOVERY.md`](./BACKUP_RECOVERY.md).

Headline targets:

| Asset       | RPO    | RTO     | Mechanism                                                              |
|-------------|--------|---------|------------------------------------------------------------------------|
| PostgreSQL  | ≤ 1 h  | ≤ 30 min| Daily `pg_dump` (custom format) + continuous WAL archiving to S3 (PITR)|
| Redis       | ≤ 24 h | ≤ 10 min| Nightly `BGSAVE` RDB snapshot to S3                                    |
| User media  | ≤ 24 h | ≤ 10 min| `aws s3 sync` to a separate region/bucket; versioning on               |

What's wired up:

- **Backup image** — `deploy/backup/Dockerfile`. Bundles `pg_dump`,
  `redis-cli`, `awscli` and the helper scripts under
  `deploy/backup/scripts/`.
- **Helm jobs** — `deploy/helm/telegram-ai-agent/templates/backup/*.yaml`.
  Enable with `--set backup.enabled=true` and the S3 destination block (see
  `values-production.yaml`). Renders five `CronJob`s: postgres dump, redis
  RDB, media sync, prune, and quarterly verify.
- **Raw manifests** — `deploy/k8s/backup/` for non-Helm clusters.
- **Compose fallback** — `docker/compose.backup.yml` layers a long-running
  `backup-supervisor` (supercronic) on top of `docker/compose.prod.yml`.
- **Encryption** — uploads enforce SSE-KMS when `BACKUP_KMS_KEY_ID` is set,
  otherwise SSE-S3 (`AES256`). Plaintext uploads are refused.
- **Retention** — `BACKUP_RETENTION_DAYS` (default `30`) for full backups;
  `BACKUP_WAL_RETENTION_DAYS` (default `7`) for WAL segments. Enforced both
  by the daily prune CronJob and by the bucket-level S3 lifecycle policy
  documented in the runbook.
- **Restore drills** — `verify-backup.sh` restores the latest dump into an
  ephemeral `backup_verify` database, smoke-tests the tables listed in
  `BACKUP_SMOKE_TABLES`, and tears the DB down. Scheduled quarterly
  (`0 6 1 1,4,7,10 *`) via the `tgai-backup-verify` CronJob.

For day-to-day operational commands (kick off an ad-hoc backup, restore a
specific dump, recover from a corrupted Postgres volume, etc.) jump straight
into [`docs/BACKUP_RECOVERY.md`](./BACKUP_RECOVERY.md).

---

## 11. Security checklist before going live

- [ ] All secrets sourced from sealed-secrets or ExternalSecret — no plain
      `Secret` YAML in git.
- [ ] `cert-manager` issued real Let's Encrypt certs (not `…-staging`) for
      production hosts. `kubectl describe certificate -n tgai-prod` shows
      `Ready=True`.
- [ ] HPA active: `kubectl get hpa -n tgai-prod` shows non-zero current
      replicas.
- [ ] PodDisruptionBudget present:
      `kubectl get pdb -n tgai-prod telegram-ai-agent-backend`.
- [ ] Pods run with `runAsNonRoot: true`, `readOnlyRootFilesystem: true`,
      dropped capabilities (chart defaults — verify nothing overrode them).
- [ ] GitHub `production` environment has required reviewers configured.
- [ ] Webhook secret rotated and confirmed via Telegram `getWebhookInfo`.
