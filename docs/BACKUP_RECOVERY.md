# Backup & Disaster Recovery

End-to-end backup strategy and disaster-recovery runbook for the **Telegram
AI Agent** platform. The acceptance criteria from
[issue #33](https://github.com/labtgbot/telegram-ai-agent/issues/33) (Phase
4) are tracked at the bottom of this document.

> **TL;DR:** Daily logical Postgres dumps + 5-min WAL archiving give us
> point-in-time recovery (PITR) with an **RPO ≤ 1 h** and **RTO ≤ 30 min**.
> Redis is snapshotted daily; media buckets are mirrored daily. Restore
> drills run quarterly and alert on failure. Everything ships encrypted
> (KMS) to S3-compatible storage with a 30-day retention.

---

## 1. Targets

| Target | Value | Rationale |
|--------|-------|-----------|
| **RPO** (max acceptable data loss) | **≤ 1 hour** | WAL is archived every minute under normal load; a 1-hour ceiling tolerates a one-off provider blip. |
| **RTO** (time to running again) | **≤ 30 minutes** | Logical dumps are < 5 GB at current scale and `pg_restore --jobs=4` finishes in ~5 min on managed PG. |
| **Retention** | 30 days (dumps), 7 days (WAL) | Phase 4 acceptance criterion. WAL drives the PITR window. |
| **Encryption at rest** | SSE-KMS (mandatory in prod) | Falls back to SSE-S3 (AES-256) when no KMS key is configured; plaintext uploads are rejected by `lib/common.sh`. |
| **Restore drill cadence** | Quarterly | Cron `0 6 1 1,4,7,10 *` — runs against a throw-away DB and alerts on failure. |

---

## 2. What we back up

| Asset | Mechanism | Frequency | Destination |
|-------|-----------|-----------|-------------|
| PostgreSQL — logical dump | `pg_dump --format=custom` | daily 02:00 UTC | `s3://$BACKUP_S3_BUCKET/postgres/full/YYYY/MM/DD/…` |
| PostgreSQL — WAL | `archive_command` → `postgres-wal-archive.sh` | continuous (each ~16 MiB segment) | `s3://$BACKUP_S3_BUCKET/postgres/wal/…` |
| Redis | `BGSAVE` + RDB upload | daily 02:30 UTC | `s3://$BACKUP_S3_BUCKET/redis/YYYY/MM/DD/…` |
| User-uploaded media | `aws s3 sync` (with object versioning on dst) | daily 03:00 UTC | `s3://$BACKUP_S3_BUCKET/media/…` |
| Retention enforcement | `prune-backups.sh` | daily 04:00 UTC | n/a |
| Restore drill | `verify-backup.sh` | quarterly 06:00 UTC | restores into ephemeral DB `backup_verify` |

All schedules are configurable per environment — see
[`values-production.yaml`](../deploy/helm/telegram-ai-agent/values-production.yaml)
and [`values-staging.yaml`](../deploy/helm/telegram-ai-agent/values-staging.yaml).

---

## 3. Architecture

```
┌─────────────────┐    pg_dump      ┌───────────────────────┐
│  postgres       │ ─────────────▶  │ tgai-postgres-backup  │ ─┐
│  (managed/HA)   │    pg_receivewal│   (CronJob)           │  │
│                 │ ─────────────▶  │                       │  │
└─────────────────┘                 └───────────────────────┘  │
                                                               │
┌─────────────────┐    BGSAVE/RDB   ┌───────────────────────┐  │ SSE-KMS
│  redis          │ ─────────────▶  │ tgai-redis-backup     │ ─┤
│                 │                 │   (CronJob)           │  │
└─────────────────┘                 └───────────────────────┘  │
                                                               ▼
┌─────────────────┐    s3 sync      ┌───────────────────────┐  ┌──────────────────┐
│  media bucket   │ ─────────────▶  │ tgai-media-sync       │  │ s3://backups/    │
│  (app S3)       │                 │   (CronJob)           │─▶│   postgres/full/ │
└─────────────────┘                 └───────────────────────┘  │   postgres/wal/  │
                                                               │   redis/         │
┌─────────────────┐                 ┌───────────────────────┐  │   media/         │
│ throw-away DB   │ ◀───── pg_restore   tgai-backup-verify  │◀─│  (versioned,     │
│ backup_verify   │                 │   (quarterly)         │  │   KMS-encrypted) │
└─────────────────┘                 └───────────────────────┘  └──────────────────┘
                                                               ▲
                                                               │
                                                  ┌───────────────────────┐
                                                  │ tgai-backup-prune     │
                                                  │ daily retention       │
                                                  └───────────────────────┘
```

---

## 4. Provisioning the backup bucket

The bucket lives outside the Helm chart — provision it once per environment
with Terraform / Pulumi / `aws s3api`:

```bash
aws s3api create-bucket \
  --bucket tgai-prod-backups \
  --region eu-central-1 \
  --create-bucket-configuration LocationConstraint=eu-central-1

# Mandatory: versioning + default KMS encryption.
aws s3api put-bucket-versioning \
  --bucket tgai-prod-backups \
  --versioning-configuration Status=Enabled

aws s3api put-bucket-encryption \
  --bucket tgai-prod-backups \
  --server-side-encryption-configuration '{
    "Rules":[{"ApplyServerSideEncryptionByDefault":{
      "SSEAlgorithm":"aws:kms",
      "KMSMasterKeyID":"alias/tgai-prod-backups"}}]}'

# Block public access — non-negotiable for backups.
aws s3api put-public-access-block \
  --bucket tgai-prod-backups \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# Object Lock (compliance mode) is strongly recommended for production —
# protects against ransomware-style "encrypt and delete" attacks.
```

The bucket's lifecycle policy is what physically deletes objects after
retention; the in-job prune is best-effort.

```bash
aws s3api put-bucket-lifecycle-configuration \
  --bucket tgai-prod-backups \
  --lifecycle-configuration '{
    "Rules":[
      {"ID":"expire-postgres-full","Status":"Enabled",
       "Filter":{"Prefix":"postgres/full/"},
       "Expiration":{"Days":30},
       "NoncurrentVersionExpiration":{"NoncurrentDays":7}},
      {"ID":"expire-postgres-wal","Status":"Enabled",
       "Filter":{"Prefix":"postgres/wal/"},
       "Expiration":{"Days":7}},
      {"ID":"expire-redis","Status":"Enabled",
       "Filter":{"Prefix":"redis/"},
       "Expiration":{"Days":30}}
    ]}'
```

### IAM (when using static keys)

Minimum-permission policy for the backup IAM user. **Prefer IRSA / workload
identity** on EKS / GKE and skip the user entirely.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:PutObjectTagging", "s3:GetObject",
                 "s3:DeleteObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::tgai-prod-backups",
        "arn:aws:s3:::tgai-prod-backups/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["kms:Encrypt", "kms:Decrypt", "kms:GenerateDataKey"],
      "Resource": "arn:aws:kms:eu-central-1:<account>:key/<key-uuid>"
    }
  ]
}
```

---

## 5. WAL archiving (PITR)

Logical dumps alone can lose up to 24 h of writes — they cap RPO at the
backup interval. For RPO ≤ 1 h we need WAL archiving + a recent base backup.

Two paths, depending on whether the database is self-hosted or managed:

### 5.1 Managed Postgres (recommended)

AWS RDS, Cloud SQL, Azure DB, Crunchy Bridge, Aiven, Neon all expose
provider-side PITR. Enable it:

- **RDS**: `BackupRetentionPeriod = 30`, automated backups on. PITR window =
  `latest restorable time` shown in the console.
- **Cloud SQL**: enable *Point-in-time recovery* + retain ≥ 7 days of binary
  logs.
- **Aiven / Crunchy**: PITR is on by default; just set retention to 30 days.

The Helm chart's WAL archiving config is then **off** — let the provider do
it, and use this repo's logical dumps as a *secondary*, provider-independent
backup (escape-hatch when the provider account is compromised).

### 5.2 Self-hosted Postgres

When you run Postgres yourself (e.g. inside the cluster, on a VM):

```ini
# postgresql.conf — driven by your config tooling, NOT this repo:
wal_level = replica
archive_mode = on
archive_command = 'BACKUP_S3_BUCKET=tgai-prod-backups \
                   BACKUP_S3_REGION=eu-central-1 \
                   /opt/tgai/backup/postgres-wal-archive.sh %p %f'
archive_timeout = 60s        # force a segment every minute to cap RPO at ~60s
```

Bundle `postgres-wal-archive.sh` into the Postgres image (or mount it from a
ConfigMap if running in K8s). The script enforces KMS encryption and retries
via Postgres's normal `archive_command` retry loop.

A nightly base backup is required for PITR — use `pg_basebackup` or
`pgbackrest stanza-create && pgbackrest backup`. The schedule lives outside
this chart; add it as a separate CronJob in the same `tgai-backup`
namespace.

### 5.3 RPO/RTO maths

- WAL segment forced every 60 s ⇒ **worst-case RPO ≈ 60 s** (assuming the
  archive_command never fails for > 60 s in a row).
- 30-day retention of logical dumps gives a deep escape-hatch in case the
  WAL archive is corrupted.
- `pg_restore --jobs=4` against a 5 GB dump runs in ~5 minutes on a
  4-vCPU managed PG instance ⇒ **RTO ≈ 10–15 min** for "restore from last
  logical dump", **≈ 25 min** when WAL replay needs to catch up to a specific
  point-in-time.

---

## 6. Day-to-day operations

### 6.1 Inspect the latest backup

```bash
# Kubernetes: trigger the CronJob ad-hoc.
kubectl create job --from=cronjob/telegram-ai-agent-backup-postgres \
  -n tgai-prod manual-$(date +%s)
kubectl logs -f -n tgai-prod -l backup.tgai/job=postgres-full --tail=-1

# Docker compose:
docker compose -f docker/compose.prod.yml -f docker/compose.backup.yml \
  --profile backup-runner run --rm backup-runner postgres-backup.sh

# Verify the pointer:
aws s3 cp s3://tgai-prod-backups/postgres/full/latest -
```

### 6.2 Restore drill (manual)

Restore the latest logical dump into a throw-away database. Safe to run on
production — it never touches the live `telegram_ai_agent` database.

```bash
kubectl create job --from=cronjob/telegram-ai-agent-backup-verify \
  -n tgai-prod drill-$(date +%s)
```

Failure surfaces in CronJob status and (if configured) Slack via
`BACKUP_NOTIFY_WEBHOOK`.

### 6.3 Adjust schedules

Tune `backup.<job>.schedule` in `values-{staging,production}.yaml` and run
`helm upgrade`. The cron strings are stock Kubernetes CronJob expressions
(no seconds field, UTC).

---

## 7. Disaster recovery — full restore (RTO ≤ 30 min)

### 7.1 Scenario A — primary database lost, app still running

1. **Confirm scope.** Has data been written since the last good dump?
   - If yes ⇒ Section 7.2 (PITR).
   - If no  ⇒ this section.
2. **Stop writes** to the application (set `backend.replicaCount=0` via
   Helm, or `docker compose stop backend`).
3. **Restore the latest dump** into a fresh DB:

   ```bash
   kubectl run -it --rm pg-restore --image=ghcr.io/labtgbot/telegram-ai-agent/backup:$VERSION \
     --env BACKUP_S3_BUCKET=tgai-prod-backups \
     --env BACKUP_S3_REGION=eu-central-1 \
     --env PGHOST=postgres.tgai-prod.svc.cluster.local \
     --env PGUSER=postgres \
     --env PGPASSWORD=$(kubectl get secret/telegram-ai-agent-backup -n tgai-prod -o jsonpath='{.data.PGPASSWORD}' | base64 -d) \
     --env PGDATABASE=telegram_ai_agent \
     -- /opt/tgai/backup/postgres-restore.sh --latest --drop --jobs 4
   ```
4. **Smoke-check.** `kubectl exec deploy/telegram-ai-agent-backend -- \
   curl -sf http://localhost:8000/api/v1/health | jq` — both `database`
   and `redis` checks must show `ok`.
5. **Scale the backend back up** (`backend.replicaCount=N`).
6. **Re-register the Telegram webhook** if the deployment URL changed
   (see DEPLOYMENT.md §6).

Expected duration: ~10–15 min on a 5 GB DB.

### 7.2 Scenario B — point-in-time restore (managed PG)

```bash
# RDS example. Adjust for your provider.
aws rds restore-db-instance-to-point-in-time \
  --source-db-instance-identifier tgai-prod \
  --target-db-instance-identifier tgai-prod-pitr-$(date +%s) \
  --restore-time 2026-03-15T14:23:00Z \
  --db-instance-class db.r6g.large \
  --no-publicly-accessible

# Once the new instance is up:
# 1. Update the application's DATABASE_URL secret to point at it.
# 2. Bounce the backend deployment (`kubectl rollout restart`).
# 3. Run the smoke checks from DEPLOYMENT.md §6.
```

Expected duration: dominated by provider provisioning time (15–25 min on
RDS). Application downtime ≈ time to swap the secret + bounce pods.

### 7.3 Scenario C — Redis lost

Redis is a cache and a short-TTL session store. Losing it is annoying but
not catastrophic — you can:

1. **Skip restore** for incidents during low traffic. The application
   re-warms naturally; expect a 5–10 min latency bump.
2. **Restore** for incidents during peak traffic:

   ```bash
   # Place the latest RDB into the Redis data dir, then restart redis.
   kubectl run -it --rm redis-restore \
     --image=ghcr.io/labtgbot/telegram-ai-agent/backup:$VERSION \
     --env BACKUP_S3_BUCKET=tgai-prod-backups \
     --env BACKUP_S3_REGION=eu-central-1 \
     -- /opt/tgai/backup/redis-restore.sh --target-dir /pvc

   # Mount /pvc onto the Redis PVC, then:
   kubectl rollout restart statefulset/redis -n tgai-prod
   ```

### 7.4 Scenario D — media bucket lost

Mirror is one-way (source → backup). To recover:

```bash
aws s3 sync \
  --source-region eu-central-1 \
  s3://tgai-prod-backups/media \
  s3://tgai-prod-media
```

With object versioning on the destination bucket, you can also recover
*individual* files at point-in-time using `aws s3api list-object-versions`.

---

## 8. Quarterly restore drill (mandatory)

The `verify-backup` CronJob runs automatically:

- **Cluster**: `kubectl get cronjob -n tgai-prod telegram-ai-agent-backup-verify`
- **Compose**: handled by `backup-supervisor`'s crontab entry.

The drill:

1. Drops + recreates DB `backup_verify`.
2. Downloads the latest logical dump (checksum-verified).
3. Restores into `backup_verify`.
4. Runs `SELECT count(*) FROM <BACKUP_SMOKE_TABLES>` — every table must
   return > 0 rows.
5. Drops the ephemeral DB.
6. Emits a Slack `INFO` (success) or `ERROR` (failure) notification.

**Manual drill** — required at least once per quarter regardless of cron:

```bash
# K8s
kubectl create job --from=cronjob/telegram-ai-agent-backup-verify \
  -n tgai-prod manual-drill-$(date -u +%Y%m%dT%H%M%SZ)

# Compose
docker compose -f docker/compose.prod.yml -f docker/compose.backup.yml \
  --profile backup-runner run --rm backup-runner verify-backup.sh
```

Record the result (timestamp + dump key + smoke counts) in the team's
on-call rotation document.

---

## 9. Security checklist

- [ ] Backup bucket has versioning + KMS default encryption + public access
      block enabled.
- [ ] Backup IAM role / IRSA grants **only** the permissions in §4 — no
      `s3:*`, no `kms:*Decrypt*` against unrelated keys.
- [ ] `BACKUP_NOTIFY_WEBHOOK` is a low-blast-radius channel (an `ops-alerts`
      channel, not `#general`) so failures aren't lost.
- [ ] `verify-backup` ran successfully in the current quarter — link in the
      release runbook.
- [ ] The Postgres backup user has **read-only** access (SELECT + USAGE on
      schemas, no DDL). Document the role in `backend/scripts/seed.py` or
      equivalent.
- [ ] Restore drills include an explicit "drop the ephemeral DB" step so
      verify runs don't accumulate cruft.
- [ ] Lifecycle policy is wired (object-level retention) — in-script prune
      is the safety net, **not** the policy.

---

## 10. Acceptance criteria mapping (issue #33)

| Criterion | Covered by |
|-----------|------------|
| Daily PostgreSQL snapshot + WAL archiving (PITR) | `postgres-backup.sh` (daily) + `postgres-wal-archive.sh` (continuous) / managed PG PITR (§5) |
| Retention: 30 days | `BACKUP_RETENTION_DAYS=30` + lifecycle policy (§4) |
| Backup to S3-compatible storage, KMS encryption | `lib/common.sh` — `tgai_s3_sse_args` enforces SSE-KMS / SSE-S3 |
| Regular (quarterly) restore drill | `verify-backup` CronJob — `0 6 1 1,4,7,10 *` (§8) |
| Redis backup (RDB snapshots) | `redis-backup.sh` daily (§2) |
| User-media backup (S3) | `media-sync.sh` daily (§2, §7.4) |
| DR documentation in `docs/DEPLOYMENT.md` | DEPLOYMENT.md §10 now points here; this document is the full runbook |
| RPO ≤ 1 h, RTO ≤ 30 min | §1, §5.3 |
