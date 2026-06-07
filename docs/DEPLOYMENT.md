# Deployment And Configuration Guide

This guide explains how to deploy **Telegram AI Agent**, how to configure the
application, and which hosting/database options fit different environments.
It is written for staging and production operators. For local development, use
[`README.md`](../README.md) and component README files.

The repository ships two first-class deployment paths:

1. **Kubernetes + Helm** - recommended for production and any environment that
   needs autoscaling, canary deploys, managed secrets, and HA.
2. **Single SSH server + Docker Compose** - recommended for a small production,
   staging, demos, or on-prem installs where one VM is enough.

Managed PaaS/container hosting can also work, but you must map the same
runtime variables, network paths, health checks, migrations, and webhook setup
described below.

Read this document together with:

- [`docs/PRODUCTION_DEPLOY.md`](PRODUCTION_DEPLOY.md) - launch-day cutover.
- [`docs/LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md) - go-live gates.
- [`docs/BACKUP_RECOVERY.md`](BACKUP_RECOVERY.md) - backup and restore runbook.
- [`docs/MONITORING.md`](MONITORING.md) - dashboards and alerts.

## Contents

1. [Application topology](#1-application-topology)
2. [Hosting options](#2-hosting-options)
3. [Database and cache options](#3-database-and-cache-options)
4. [Common prerequisites](#4-common-prerequisites)
5. [Configuration reference](#5-configuration-reference)
6. [Kubernetes deployment](#6-kubernetes-deployment)
7. [Single-host SSH deployment](#7-single-host-ssh-deployment)
8. [Managed platform deployment](#8-managed-platform-deployment)
9. [Database migrations](#9-database-migrations)
10. [Telegram and BotFather setup](#10-telegram-and-botfather-setup)
11. [Smoke checks](#11-smoke-checks)
12. [Updates and rollback](#12-updates-and-rollback)
13. [Monitoring, logs, and backups](#13-monitoring-logs-and-backups)
14. [Security checklist](#14-security-checklist)
15. [Troubleshooting](#15-troubleshooting)

---

## 1. Application topology

Production traffic normally uses three public surfaces:

| Surface | Example URL | Serves | Internal target |
|---------|-------------|--------|-----------------|
| Bot API / webhook | `https://bot.example.com/api/v1/...` | FastAPI REST API and Telegram webhook | `backend:8000` |
| Mini App | `https://bot.example.com/` | React/Vite static bundle opened inside Telegram | `mini-app:80` |
| Admin dashboard | `https://admin.example.com/` | Next.js CRM/admin UI | `admin:3001` |

Stateful services:

| Service | Required | Purpose |
|---------|----------|---------|
| PostgreSQL | Yes | Users, transactions, chat history, analytics, audit logs |
| Redis | Yes | Rate limits, auth/login state, caches, short-lived workflow state |
| Object storage | Optional at first, recommended for production | Backups and media sync |

External APIs:

- Telegram Bot API.
- One or more AI providers: Gemini, Anthropic, OpenAI.
- Composio MCP, when real tool execution is enabled.
- Sentry, Prometheus/Grafana, and alerting integrations when observability is
  enabled.

---

## 2. Hosting options

Choose the smallest platform that still satisfies your uptime, restore, and
operations requirements.

| Option | Best for | Pros | Tradeoffs |
|--------|----------|------|-----------|
| Kubernetes + Helm | Production, HA staging, multi-service teams | Replicas, HPA, ingress, cert-manager, canary/blue-green, CronJobs, secrets integrations | Requires cluster operations knowledge |
| Single SSH server + Docker Compose | Small production, demos, staging, on-prem | Simple, cheap, one host to manage, included Caddy TLS | No native HA; host loss means downtime until restore |
| Managed container platform | Teams using Render/Fly/Railway/Cloud Run/App Runner/etc. | Less infrastructure to operate | Must translate compose/Helm settings into provider-specific services |
| Static frontend + managed backend | Mini App/Admin on CDN, backend in a container platform | Good static performance and simpler frontend scaling | Frontend env is build-time for Vite; routing/CORS must be explicit |
| Fully managed Kubernetes | Production without self-managed control plane | Same Helm flow with less cluster maintenance | Higher cost than one VM |

Recommended default:

- **Staging**: single SSH server or a small Kubernetes namespace.
- **Production with early traffic**: managed PostgreSQL + managed Redis +
  either Kubernetes or one well-backed-up SSH server.
- **Production with strict uptime**: Kubernetes, managed PostgreSQL HA,
  managed Redis HA, object storage backups, and canary deploys.

---

## 3. Database and cache options

### 3.1 PostgreSQL options

| Option | When to use | Notes |
|--------|-------------|-------|
| Managed PostgreSQL | Recommended for production | Prefer PITR, automatic backups, TLS, private networking, and read replicas for analytics growth. |
| Compose PostgreSQL on the SSH host | Small installs and staging | Easiest path; use volume backups and test restores. Host failure requires restoring the whole VM or volume. |
| In-cluster PostgreSQL | Dev/staging clusters | Avoid for production unless your team already operates stateful workloads well. |
| Existing corporate PostgreSQL | On-prem/enterprise | Confirm async connection string, firewall, TLS policy, backup owner, and migration permissions. |

Required SQLAlchemy URL format:

```bash
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/telegram_ai_agent
```

Alembic automatically converts this to a sync driver for offline migration
operations where needed.

### 3.2 Redis options

| Option | When to use | Notes |
|--------|-------------|-------|
| Managed Redis | Recommended for production | Prefer private networking, persistence where available, and memory alerts. |
| Compose Redis on the SSH host | Small installs and staging | The bundled compose file enables append-only persistence. |
| In-cluster Redis | Dev/staging clusters | Fine when data loss is acceptable or backups are configured. |

Required URL format:

```bash
REDIS_URL=redis://HOST:6379/0
# or, when password-protected:
REDIS_URL=redis://:PASSWORD@HOST:6379/0
```

### 3.3 Sizing starter points

| Environment | PostgreSQL | Redis | Backend replicas/workers |
|-------------|------------|-------|--------------------------|
| Staging/demo | 1 vCPU / 1-2 GiB RAM | 256-512 MiB | 1 backend |
| Small production | 2 vCPU / 4 GiB RAM | 512 MiB-1 GiB | Compose backend with 2-4 Uvicorn workers |
| HA production | Managed HA tier | Managed HA tier | 3+ Kubernetes replicas with HPA |

Tune PostgreSQL pool settings per backend process:

```bash
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10
DB_POOL_TIMEOUT=10
DB_POOL_RECYCLE=1800
DB_STATEMENT_CACHE_SIZE=1024
```

Total possible DB connections are roughly:

```text
backend_replicas_or_processes * (DB_POOL_SIZE + DB_MAX_OVERFLOW)
```

Keep this below the database plan limit with room for migrations, admin tools,
and backup jobs.

---

## 4. Common prerequisites

Before any deployment path:

1. Create a Telegram bot with `@BotFather`; save `TELEGRAM_BOT_TOKEN` and bot
   username.
2. Choose public domains:
   - `bot.example.com` for API, webhook, and Mini App.
   - `admin.example.com` for the admin dashboard.
3. Prepare provider API keys that are enabled in your product:
   - `GEMINI_API_KEY`
   - `ANTHROPIC_API_KEY`
   - `OPENAI_API_KEY`
   - `COMPOSIO_API_KEY`
4. Create strong secrets:
   - `ADMIN_JWT_SECRET`
   - `APP_SECRET`
   - `TELEGRAM_WEBHOOK_SECRET`
   - database and Redis passwords, if self-hosted.
5. Decide where backups go. Production should have an S3-compatible bucket
   with lifecycle/retention rules.
6. Decide the released image tag. Avoid `latest` in production; use an
   immutable version such as `0.1.0` or a commit SHA.

Generate local secrets with:

```bash
openssl rand -hex 32
openssl rand -base64 48
```

---

## 5. Configuration reference

### 5.1 Backend environment variables

Required in production:

| Variable | Required | Description |
|----------|----------|-------------|
| `APP_ENV` | Yes | Use `production` or `staging`; non-dev rejects placeholder admin secrets. |
| `APP_DEBUG` | Yes | Use `false` outside local development. |
| `DATABASE_URL` | Yes | Async SQLAlchemy URL, usually `postgresql+asyncpg://...`. |
| `REDIS_URL` | Yes | Redis URL. |
| `TELEGRAM_BOT_TOKEN` | Yes | Bot token from BotFather. |
| `TELEGRAM_BOT_USERNAME` | Recommended | Bot username without `@`; used in referral links. |
| `TELEGRAM_WEBHOOK_SECRET` | Yes | Sent to Telegram and checked on webhook requests. |
| `TELEGRAM_UPDATE_IDEMPOTENCY_TTL_SECONDS` | Optional | Redis TTL for processed Telegram `update_id` keys; defaults to 7 days. |
| `TELEGRAM_MINI_APP_URL` | Yes | Public Mini App URL, normally `https://bot.example.com/`. |
| `ADMIN_JWT_SECRET` | Yes | Long random string for admin JWT signing. |
| `ADMIN_SUPER_TELEGRAM_IDS` | Yes for admin access | Comma-separated Telegram user IDs that become `super_admin`. |
| `TRUSTED_PROXY_IPS` | Recommended behind a reverse proxy | Comma-separated IP/CIDR allowlist for Caddy/Ingress/LB peers whose `X-Forwarded-For` headers may be used. Empty ignores XFF and records the direct peer. |
| `PAYMENT_PROVIDER_TOKEN` | Required when payments need a provider token | Telegram provider token, if not using Stars-only flow. |
| `PAYMENT_CURRENCY` | Yes | Defaults to `XTR` for Telegram Stars. |

AI/tooling keys:

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | If Gemini is enabled | Gemini API key. |
| `ANTHROPIC_API_KEY` | If Anthropic is enabled | Anthropic API key. |
| `OPENAI_API_KEY` | If OpenAI is enabled | OpenAI API key. |
| `COMPOSIO_API_KEY` | If real Composio calls are enabled | Empty value switches the backend to mock Composio client behavior. |
| `COMPOSIO_DEFAULT_USER_ID` | Optional | Default connected account/user for Composio tool calls. |
| `COMPOSIO_DEFAULT_TOOLKITS` | Optional | Comma-separated toolkit list. |

Operational settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Backend log level. |
| `LOG_FORMAT` | `json` | Use `json` in production, `console` locally. |
| `API_V1_PREFIX` | `/api/v1` | API prefix. |
| `HEALTH_CHECK_TIMEOUT` | `2.0` | Per dependency timeout for health checks. |
| `METRICS_ENABLED` | `true` | Expose Prometheus metrics. |
| `METRICS_PATH` | `/metrics` | Metrics path. |
| `SENTRY_DSN` | empty | Empty disables Sentry. |
| `SENTRY_ENVIRONMENT` | `APP_ENV` | Sentry environment tag. |
| `SENTRY_RELEASE` | app version | Release tag. |

Admin login settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `ADMIN_JWT_ALGORITHM` | `HS256` | JWT signing algorithm. |
| `ADMIN_ACCESS_TOKEN_TTL` | `900` | Access token TTL in seconds. |
| `ADMIN_REFRESH_TOKEN_TTL` | `604800` | Refresh token TTL in seconds. |
| `ADMIN_LOGIN_CODE_TTL` | `300` | One-time login code TTL. |
| `ADMIN_LOGIN_CODE_LENGTH` | `6` | Login code length. |
| `ADMIN_LOGIN_MAX_ATTEMPTS` | `5` | Failed attempts before invalidation. |
| `TOTP_ISSUER` | `Telegram AI Agent` | Issuer shown in authenticator apps. |

### 5.2 Frontend environment variables

Mini App (Vite) variables are **build-time** variables:

```bash
VITE_API_BASE_URL=https://bot.example.com/api/v1
VITE_SENTRY_DSN=
VITE_SENTRY_ENVIRONMENT=production
VITE_SENTRY_RELEASE=0.1.0
```

For the single-domain Caddy setup, `VITE_API_BASE_URL=/api/v1` is also valid
when the Mini App is served from `https://bot.example.com/`.

Admin dashboard variables:

```bash
# Browser-visible URL. Use the public API endpoint.
NEXT_PUBLIC_API_BASE_URL=https://bot.example.com/api/v1

# Server-side URL from the admin container/pod. Use the internal service when available.
API_BASE_URL=http://backend:8000/api/v1

ADMIN_JWT_SECRET=<same value as backend>
ADMIN_JWT_ALGORITHM=HS256
NEXT_PUBLIC_SENTRY_DSN=
SENTRY_DSN=
```

### 5.3 Docker Compose deployment variables

The production compose file also reads:

| Variable | Description |
|----------|-------------|
| `DOMAIN` | Public bot/API/Mini App domain used by Caddy. |
| `ADMIN_DOMAIN` | Public admin dashboard domain used by Caddy. |
| `ACME_EMAIL` | Email used for Let's Encrypt account registration. |
| `CADDY_DATA_DIR` | Host directory for Caddy certificates/storage, owned by UID/GID `65534`. |
| `CADDY_CONFIG_DIR` | Host directory for Caddy autosaved config, owned by UID/GID `65534`. |
| `POSTGRES_PASSWORD` | Password for the bundled Compose PostgreSQL service. |
| `REDIS_PASSWORD` | Password required by the bundled Compose Redis service. |
| `BACKEND_IMAGE` | Backend image reference. |
| `MINI_APP_IMAGE` | Mini App image reference. |
| `ADMIN_IMAGE` | Admin image reference. |

Use explicit tags:

```bash
BACKEND_IMAGE=ghcr.io/labtgbot/telegram-ai-agent/backend:0.1.0
MINI_APP_IMAGE=ghcr.io/labtgbot/telegram-ai-agent/mini-app:0.1.0
ADMIN_IMAGE=ghcr.io/labtgbot/telegram-ai-agent/admin:0.1.0
```

---

## 6. Kubernetes deployment

Kubernetes deployment uses the Helm chart in
[`deploy/helm/telegram-ai-agent`](../deploy/helm/telegram-ai-agent).

### 6.1 Cluster prerequisites

Install once per cluster:

- Kubernetes `>=1.27`.
- Ingress controller, default chart assumption: `nginx`.
- `cert-manager` for ACME certificates.
- `sealed-secrets` or `external-secrets` for production secrets.
- Optional `argo-rollouts` for canary/blue-green backend deploys.
- Optional Prometheus/Grafana/Loki/Sentry integrations.

Workstation tools:

```bash
kubectl version --client
helm version
```

### 6.2 Create namespace

```bash
kubectl create namespace tgai-prod
```

Use `tgai-staging` for staging.

### 6.3 Install cert-manager issuers

```bash
kubectl apply -f deploy/k8s/cert-manager/cluster-issuer-staging.yaml
kubectl apply -f deploy/k8s/cert-manager/cluster-issuer-prod.yaml
```

`values-staging.yaml` uses `letsencrypt-staging`; production uses
`letsencrypt-prod`.

### 6.4 Provision secrets

The chart does not generate real production secrets. Create a Kubernetes
Secret named `telegram-ai-agent-backend` with at least:

```bash
kubectl -n tgai-prod create secret generic telegram-ai-agent-backend \
  --from-literal=TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
  --from-literal=TELEGRAM_WEBHOOK_SECRET="$TELEGRAM_WEBHOOK_SECRET" \
  --from-literal=TELEGRAM_MINI_APP_URL="https://bot.example.com/" \
  --from-literal=APP_SECRET="$APP_SECRET" \
  --from-literal=ADMIN_JWT_SECRET="$ADMIN_JWT_SECRET" \
  --from-literal=ADMIN_SUPER_TELEGRAM_IDS="$ADMIN_SUPER_TELEGRAM_IDS" \
  --from-literal=DATABASE_URL="$DATABASE_URL" \
  --from-literal=REDIS_URL="$REDIS_URL" \
  --from-literal=COMPOSIO_API_KEY="$COMPOSIO_API_KEY" \
  --from-literal=GEMINI_API_KEY="$GEMINI_API_KEY" \
  --from-literal=ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  --from-literal=OPENAI_API_KEY="$OPENAI_API_KEY" \
  --from-literal=PAYMENT_PROVIDER_TOKEN="$PAYMENT_PROVIDER_TOKEN" \
  --dry-run=client -o yaml
```

Do not commit this plain Secret manifest. For GitOps, pipe it through
`kubeseal`, or use External Secrets:

```bash
kubectl apply -f deploy/k8s/secrets/secret-store.example.yaml
kubectl apply -f deploy/k8s/secrets/external-secret.example.yaml
```

### 6.5 Review values

Edit only environment-specific overlays:

- `deploy/helm/telegram-ai-agent/values-staging.yaml`
- `deploy/helm/telegram-ai-agent/values-production.yaml`

Check:

- `ingress.hosts` match real DNS names.
- `image.tag` is set by the release command or CI.
- `backend.replicaCount`, resources, and HPA match capacity.
- `backup.enabled` and S3 settings are correct for production.
- `backend.rollout.enabled=true` only after Argo Rollouts is installed.

Render before applying:

```bash
helm lint deploy/helm/telegram-ai-agent \
  -f deploy/helm/telegram-ai-agent/values.yaml \
  -f deploy/helm/telegram-ai-agent/values-production.yaml

helm template telegram-ai-agent deploy/helm/telegram-ai-agent \
  --namespace tgai-prod \
  -f deploy/helm/telegram-ai-agent/values.yaml \
  -f deploy/helm/telegram-ai-agent/values-production.yaml \
  --set image.tag=0.1.0 > /tmp/tgai-prod.yaml
```

### 6.6 Deploy

```bash
helm upgrade --install telegram-ai-agent deploy/helm/telegram-ai-agent \
  --namespace tgai-prod --create-namespace \
  -f deploy/helm/telegram-ai-agent/values.yaml \
  -f deploy/helm/telegram-ai-agent/values-production.yaml \
  --set image.tag=0.1.0 \
  --atomic --wait --timeout 10m
```

For staging:

```bash
helm upgrade --install telegram-ai-agent deploy/helm/telegram-ai-agent \
  --namespace tgai-staging --create-namespace \
  -f deploy/helm/telegram-ai-agent/values.yaml \
  -f deploy/helm/telegram-ai-agent/values-staging.yaml \
  --set image.tag=0.1.0 \
  --wait --timeout 5m
```

### 6.7 Run migrations

```bash
kubectl -n tgai-prod exec deploy/telegram-ai-agent-backend -- \
  alembic upgrade head
```

See [Database migrations](#9-database-migrations) before shipping
non-additive schema changes.

### 6.8 Verify rollout

```bash
kubectl -n tgai-prod get pods
kubectl -n tgai-prod get ingress
kubectl -n tgai-prod describe certificate
```

If Argo Rollouts is enabled:

```bash
kubectl argo rollouts get rollout telegram-ai-agent-backend -n tgai-prod -w
kubectl argo rollouts promote telegram-ai-agent-backend -n tgai-prod
```

Abort on bad signals:

```bash
kubectl argo rollouts abort telegram-ai-agent-backend -n tgai-prod
```

---

## 7. Single-host SSH deployment

This path uses [`docker/compose.prod.yml`](../docker/compose.prod.yml) and
[`docker/Caddyfile.prod`](../docker/Caddyfile.prod). Caddy terminates TLS,
routes `/api/*` to the backend, serves the Mini App on the main domain, and
serves the admin dashboard on a separate domain.

### 7.1 Server requirements

Starter production VM:

- Ubuntu 24.04 LTS or Debian 12/13.
- 2 vCPU, 4 GiB RAM minimum for small traffic.
- 30+ GiB SSD.
- Public IPv4, and IPv6 if available.
- Ports `22`, `80`, and `443` reachable.
- Outbound access to GHCR, Telegram, AI providers, and package registries.

For higher traffic, move PostgreSQL and Redis to managed services or move to
Kubernetes before vertically scaling the VM too far.

### 7.2 DNS

Create records before starting Caddy:

```text
bot.example.com    A/AAAA -> server IP
admin.example.com  A/AAAA -> server IP
```

Wait until both resolve from outside the server:

```bash
dig +short bot.example.com
dig +short admin.example.com
```

### 7.3 Create a deploy user

Run as root or through your cloud console:

```bash
adduser deploy
usermod -aG sudo deploy
```

Copy your SSH key:

```bash
ssh-copy-id deploy@YOUR_SERVER_IP
```

Log in:

```bash
ssh deploy@YOUR_SERVER_IP
```

### 7.4 Install Docker and basic tools

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git ufw
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
```

Log out and back in so the `docker` group applies. Verify:

```bash
docker version
docker compose version
```

Enable firewall:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable
sudo ufw status
```

### 7.5 Clone the repository

```bash
sudo mkdir -p /opt/telegram-ai-agent
sudo chown deploy:deploy /opt/telegram-ai-agent
git clone https://github.com/labtgbot/telegram-ai-agent.git /opt/telegram-ai-agent/app
cd /opt/telegram-ai-agent/app
git checkout main
```

For a release tag:

```bash
git fetch --tags
git checkout v0.1.0
```

### 7.6 Create `.env.prod`

Prepare the persistent Caddy directories for the non-root Caddy container:

```bash
sudo install -d -o 65534 -g 65534 -m 0750 /opt/telegram-ai-agent/caddy/data
sudo install -d -o 65534 -g 65534 -m 0750 /opt/telegram-ai-agent/caddy/config
```

```bash
cp .env.example .env.prod
chmod 600 .env.prod
$EDITOR .env.prod
```

Minimum production values for the bundled Compose stack:

```bash
DOMAIN=bot.example.com
ADMIN_DOMAIN=admin.example.com
ACME_EMAIL=ops@example.com
CADDY_DATA_DIR=/opt/telegram-ai-agent/caddy/data
CADDY_CONFIG_DIR=/opt/telegram-ai-agent/caddy/config

APP_ENV=production
APP_DEBUG=false
LOG_FORMAT=json

POSTGRES_PASSWORD=<random database password>
REDIS_PASSWORD=<random redis password>
DATABASE_URL=postgresql+asyncpg://postgres:<same password>@postgres:5432/telegram_ai_agent
REDIS_URL=redis://:<same redis password>@redis:6379/0

TELEGRAM_BOT_TOKEN=<token from BotFather>
TELEGRAM_BOT_USERNAME=<bot username without @>
TELEGRAM_WEBHOOK_SECRET=<random secret>
TELEGRAM_MINI_APP_URL=https://bot.example.com/

ADMIN_JWT_SECRET=<random secret>
ADMIN_SUPER_TELEGRAM_IDS=123456789
API_BASE_URL=http://backend:8000/api/v1
NEXT_PUBLIC_API_BASE_URL=https://bot.example.com/api/v1

GEMINI_API_KEY=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
COMPOSIO_API_KEY=

PAYMENT_CURRENCY=XTR
PAYMENT_PROVIDER_TOKEN=

BACKEND_IMAGE=ghcr.io/labtgbot/telegram-ai-agent/backend:0.1.0
MINI_APP_IMAGE=ghcr.io/labtgbot/telegram-ai-agent/mini-app:0.1.0
ADMIN_IMAGE=ghcr.io/labtgbot/telegram-ai-agent/admin:0.1.0
```

If GHCR packages are private, authenticate once:

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin
```

The `GITHUB_TOKEN` needs package read access.

### 7.7 Pull and start services

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod pull
docker compose -f docker/compose.prod.yml --env-file .env.prod up -d
```

Inspect health:

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod ps
docker compose -f docker/compose.prod.yml --env-file .env.prod logs --tail=100 backend
docker compose -f docker/compose.prod.yml --env-file .env.prod logs --tail=100 caddy
```

### 7.8 Run database migrations

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod exec backend \
  alembic upgrade head
```

### 7.9 Register the Telegram webhook

```bash
source .env.prod
curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://${DOMAIN}/api/v1/bot/webhook" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

Confirm:

```bash
curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

### 7.10 Configure BotFather

Run the helper from the repo:

```bash
TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
TELEGRAM_BOT_USERNAME="$TELEGRAM_BOT_USERNAME" \
TELEGRAM_MINI_APP_URL="https://${DOMAIN}/" \
  python -m scripts.configure_botfather
```

Or configure manually in `@BotFather`:

1. `/setdomain` -> `https://bot.example.com`
2. `/setmenubutton` -> Web App URL `https://bot.example.com/`
3. `/setcommands` -> publish the supported bot commands.

### 7.11 Backups on SSH server

The simplest manual backup:

```bash
mkdir -p backups
docker compose -f docker/compose.prod.yml --env-file .env.prod exec postgres \
  pg_dump -U postgres -d telegram_ai_agent --format=custom \
  --file=/backups/telegram_ai_agent-$(date -u +%Y%m%dT%H%M%SZ).dump
```

Recommended production backup path:

```bash
docker compose \
  -f docker/compose.prod.yml \
  -f docker/compose.backup.yml \
  --env-file .env.prod \
  --profile backup up -d
```

Then configure the variables described in
[`docs/BACKUP_RECOVERY.md`](BACKUP_RECOVERY.md), including S3 bucket, region,
retention, and optional notification webhook.

### 7.12 Routine operations

Tail logs:

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod logs -f backend
docker compose -f docker/compose.prod.yml --env-file .env.prod logs -f caddy
```

Restart backend after secret/config changes:

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod up -d --force-recreate backend
```

Stop stack:

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod down
```

Do not use `down -v` in production unless you intentionally want to remove
PostgreSQL/Redis volumes.

---

## 8. Managed platform deployment

When using a managed platform, create equivalent services:

| Service | Runtime | Required settings |
|---------|---------|-------------------|
| Backend | Python container | Port `8000`, health path `/api/v1/health/live`, env from section 5. |
| Mini App | Static site or nginx container | Build with `VITE_API_BASE_URL=https://bot.example.com/api/v1` or `/api/v1`. |
| Admin | Next.js container | Port `3001`, `API_BASE_URL`, `NEXT_PUBLIC_API_BASE_URL`, admin JWT env. |
| PostgreSQL | Managed DB | `DATABASE_URL` with asyncpg scheme. |
| Redis | Managed Redis | `REDIS_URL`. |

Required routing:

```text
https://bot.example.com/api/* -> backend:8000
https://bot.example.com/*     -> mini-app
https://admin.example.com/*   -> admin:3001
```

Required deploy hooks:

1. Deploy backend, Mini App, and admin images/static bundle.
2. Run `alembic upgrade head` once against the target database.
3. Register Telegram webhook.
4. Run smoke checks from section 11.

If the platform cannot run one-off commands in the backend image, run
migrations from a CI job or a trusted operator workstation with the same
`DATABASE_URL`.

---

## 9. Database migrations

Migrations live under [`backend/alembic/versions`](../backend/alembic/versions).
Run them after a new backend image is deployed and before promoting traffic for
features that depend on the new schema.

Kubernetes:

```bash
kubectl -n tgai-prod exec deploy/telegram-ai-agent-backend -- \
  alembic upgrade head
```

Docker Compose:

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod exec backend \
  alembic upgrade head
```

For risky schema changes:

1. Ship additive migration first.
2. Run migration.
3. Deploy code that uses the new schema.
4. Remove old columns/tables only in a later release after all old code is
   gone.

Before production cutover, run a dry-run against a restored snapshot as shown
in [`docs/PRODUCTION_DEPLOY.md`](PRODUCTION_DEPLOY.md).

---

## 10. Telegram and BotFather setup

### 10.1 Webhook

Set webhook:

```bash
curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=https://bot.example.com/api/v1/bot/webhook" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

Check:

```bash
curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

Expected:

- `url` matches `https://bot.example.com/api/v1/bot/webhook`.
- `last_error_message` is empty.
- `pending_update_count` is not continuously increasing.

### 10.2 Mini App

Set the Mini App URL to:

```text
https://bot.example.com/
```

The URL must be HTTPS and must match the domain allowed in BotFather.

### 10.3 Admin access

Set `ADMIN_SUPER_TELEGRAM_IDS` to the Telegram numeric IDs of initial admins.
After first login, use the admin UI for day-to-day user/role operations.

---

## 11. Smoke checks

Run after every deployment.

Backend liveness:

```bash
curl -fsS https://bot.example.com/api/v1/health/live
```

Backend readiness:

```bash
curl -fsS https://bot.example.com/api/v1/health
```

Mini App:

```bash
curl -fsSI https://bot.example.com/
```

Admin dashboard:

```bash
curl -fsSI https://admin.example.com/
```

Webhook route:

```bash
curl -fsSI https://bot.example.com/api/v1/bot/webhook
```

Telegram webhook state:

```bash
curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

Expected results:

- All public URLs return `2xx` or an expected method-specific response.
- `/api/v1/health` reports healthy database and Redis dependencies.
- Caddy/ingress certificates are valid.
- Admin login code flow works for a configured super admin.
- A test Telegram message reaches the bot and produces a response.

---

## 12. Updates and rollback

### 12.1 Kubernetes update

```bash
helm upgrade telegram-ai-agent deploy/helm/telegram-ai-agent \
  --namespace tgai-prod \
  -f deploy/helm/telegram-ai-agent/values.yaml \
  -f deploy/helm/telegram-ai-agent/values-production.yaml \
  --set image.tag=0.1.1 \
  --atomic --wait --timeout 10m
```

Rollback:

```bash
helm history telegram-ai-agent -n tgai-prod
helm rollback telegram-ai-agent <REVISION> -n tgai-prod
```

Argo Rollouts:

```bash
kubectl argo rollouts undo telegram-ai-agent-backend -n tgai-prod
```

### 12.2 SSH/Compose update

```bash
cd /opt/telegram-ai-agent/app
git fetch --tags
git checkout v0.1.1
$EDITOR .env.prod   # update BACKEND_IMAGE/MINI_APP_IMAGE/ADMIN_IMAGE tags
docker compose -f docker/compose.prod.yml --env-file .env.prod pull
docker compose -f docker/compose.prod.yml --env-file .env.prod up -d
docker compose -f docker/compose.prod.yml --env-file .env.prod exec backend \
  alembic upgrade head
```

Rollback to the previous tag:

```bash
git checkout v0.1.0
$EDITOR .env.prod
docker compose -f docker/compose.prod.yml --env-file .env.prod pull
docker compose -f docker/compose.prod.yml --env-file .env.prod up -d
```

If a migration is not backward-compatible, follow the migration-specific
rollback plan from the release notes before rolling the image back.

---

## 13. Monitoring, logs, and backups

### 13.1 Metrics

The backend exposes Prometheus metrics when `METRICS_ENABLED=true`:

```text
http://backend:8000/metrics
```

In Kubernetes, pod annotations in the Helm chart expose scrape metadata and
Prometheus should scrape pods/services inside the cluster. In Compose, scrape
the backend container on the Compose network or run the monitoring stack from
[`deploy/monitoring`](../deploy/monitoring). The production Caddy config does
not expose `/metrics` publicly.

### 13.2 Logs

Use JSON logs in production:

```bash
LOG_FORMAT=json
```

Kubernetes:

```bash
kubectl -n tgai-prod logs deploy/telegram-ai-agent-backend --tail=200
```

Compose:

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod logs --tail=200 backend
```

### 13.3 Backups

Production targets:

| Asset | RPO | RTO | Mechanism |
|-------|-----|-----|-----------|
| PostgreSQL | <= 1 h | <= 30 min | Daily logical dump + WAL/PITR where available |
| Redis | <= 24 h | <= 10 min | RDB snapshot or managed provider backup |
| User media | <= 24 h | <= 10 min | S3 sync/versioning |

Use [`docs/BACKUP_RECOVERY.md`](BACKUP_RECOVERY.md) for:

- S3 bucket setup.
- KMS/SSE encryption.
- CronJob/Compose backup runner.
- Restore drills.
- Quarterly verification.

---

## 14. Security checklist

Before going live:

- [ ] `APP_ENV=production` and `APP_DEBUG=false`.
- [ ] No placeholder secrets remain: `change-me`, empty admin JWT secret, or
      copied example passwords.
- [ ] `ADMIN_JWT_SECRET`, `APP_SECRET`, and `TELEGRAM_WEBHOOK_SECRET` are long
      random values.
- [ ] Secrets are stored in a secret manager, sealed secret, or locked-down
      `.env.prod` with mode `600`.
- [ ] TLS certificates are valid for both public domains.
- [ ] Telegram webhook uses `TELEGRAM_WEBHOOK_SECRET`.
- [ ] Database is not publicly reachable unless provider firewall/IP allowlist
      is configured.
- [ ] Redis is private-network only or password-protected.
- [ ] Backups are encrypted and restore-tested.
- [ ] Production deploy uses immutable image tags, not `latest`.
- [ ] Admin super users are explicitly listed in `ADMIN_SUPER_TELEGRAM_IDS`.
- [ ] GitHub production environment has required reviewers when using CI/CD.

---

## 15. Troubleshooting

### Backend exits immediately in production

Check for placeholder admin secret:

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod logs backend
```

Set a real `ADMIN_JWT_SECRET` and recreate the backend.

### Caddy cannot issue certificates

Verify DNS points to the host and ports are open:

```bash
dig +short bot.example.com
sudo ufw status
docker compose -f docker/compose.prod.yml --env-file .env.prod logs caddy
```

### Telegram webhook has errors

Check route and secret:

```bash
curl -fsS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
curl -fsSI https://bot.example.com/api/v1/bot/webhook
```

Re-run `setWebhook` if the URL, token, or secret changed.

### Admin dashboard calls `localhost`

Set both admin API variables:

```bash
API_BASE_URL=http://backend:8000/api/v1
NEXT_PUBLIC_API_BASE_URL=https://bot.example.com/api/v1
```

Rebuild/redeploy the admin image if `NEXT_PUBLIC_*` was baked at build time.

### Mini App cannot reach API

Confirm the Mini App was built with a public API URL:

```bash
VITE_API_BASE_URL=https://bot.example.com/api/v1
```

For same-domain Caddy deployment, `/api/v1` is valid. For separate CDN
hosting, use the full public HTTPS URL and confirm the backend accepts the
origin.

### Database migrations fail

Check the backend sees the expected database:

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod exec backend \
  python -c "from app.core.config import get_settings; print(get_settings().database_url)"
```

Then inspect Alembic state:

```bash
docker compose -f docker/compose.prod.yml --env-file .env.prod exec backend \
  alembic current
```
