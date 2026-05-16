#!/usr/bin/env bash
# Enforce backup retention.
#
# Walks the configured prefixes and deletes objects older than
# $BACKUP_RETENTION_DAYS (default 30) days. Intended to run daily.
#
# Required env: BACKUP_S3_BUCKET
# Optional:
#   BACKUP_RETENTION_DAYS    default 30
#   BACKUP_WAL_RETENTION_DAYS default 7  (WAL retention is tighter — base
#                            backups + 7 days of WAL is the PITR window we
#                            advertise)
#   BACKUP_PREFIXES          space-separated list of prefixes to prune
#                            (default: "postgres/full redis")
#   BACKUP_WAL_PREFIX        default "postgres/wal"

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

tgai_install_error_trap "prune-backups"
tgai_require_env BACKUP_S3_BUCKET

BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
BACKUP_WAL_RETENTION_DAYS="${BACKUP_WAL_RETENTION_DAYS:-7}"
BACKUP_PREFIXES="${BACKUP_PREFIXES:-postgres/full redis}"
BACKUP_WAL_PREFIX="${BACKUP_WAL_PREFIX:-postgres/wal}"

for prefix in $BACKUP_PREFIXES; do
    tgai_info "pruning s3://${BACKUP_S3_BUCKET}/${prefix}/ (>${BACKUP_RETENTION_DAYS}d)"
    tgai_prune_prefix "s3://${BACKUP_S3_BUCKET}/${prefix}/" "$BACKUP_RETENTION_DAYS"
done

tgai_info "pruning WAL s3://${BACKUP_S3_BUCKET}/${BACKUP_WAL_PREFIX}/ (>${BACKUP_WAL_RETENTION_DAYS}d)"
tgai_prune_prefix "s3://${BACKUP_S3_BUCKET}/${BACKUP_WAL_PREFIX}/" "$BACKUP_WAL_RETENTION_DAYS"

tgai_notify INFO "Backup prune OK" "retention=${BACKUP_RETENTION_DAYS}d wal=${BACKUP_WAL_RETENTION_DAYS}d"
