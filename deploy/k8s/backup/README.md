# Backup CronJobs (raw manifests)

The canonical, supported install of backup CronJobs is through the
[Helm chart](../../helm/telegram-ai-agent) (`backup.enabled=true`). This
directory exposes the same CronJobs as raw YAML for clusters that do not
use Helm — for example, a one-off restore drill in a fresh namespace, or a
disaster-recovery cluster that boots before Helm is reconciled.

| Manifest                     | What it does                                     |
|------------------------------|--------------------------------------------------|
| `namespace.yaml`             | Optional `tgai-backup` namespace                 |
| `serviceaccount.yaml`        | SA used by every backup pod                      |
| `configmap.example.yaml`     | Non-secret backup config (bucket / KMS / hosts)  |
| `secret.example.yaml`        | Placeholder for AWS creds + DB password          |
| `postgres-cronjob.yaml`      | Daily logical pg_dump → S3 (KMS-encrypted)       |
| `redis-cronjob.yaml`         | Daily Redis `BGSAVE` → S3                        |
| `media-cronjob.yaml`         | Daily `aws s3 sync` from media bucket to backup  |
| `prune-cronjob.yaml`         | Daily retention enforcement                      |
| `verify-cronjob.yaml`        | Quarterly restore drill                          |

Replace `tgai/backup:latest` with the released image tag before applying.
Pre-flight checklist:

1. Provision the destination S3 bucket with versioning + a KMS key.
2. Roll Kubernetes Secret `telegram-ai-agent-backup` with at minimum:
   - `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` (or use IRSA / workload
     identity and leave both blank).
   - `PGPASSWORD` for the backup user (read-only role on the application
     database is enough — `pg_dump` only needs SELECT and metadata).
   - `REDIS_PASSWORD` if your Redis requires auth.
   - `BACKUP_NOTIFY_WEBHOOK` for Slack / Mattermost alerts (optional).
3. `kubectl apply -f deploy/k8s/backup/`.

See [`docs/BACKUP_RECOVERY.md`](../../../docs/BACKUP_RECOVERY.md) for the full
DR runbook and RPO/RTO targets.
