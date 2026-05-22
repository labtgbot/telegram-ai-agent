#!/usr/bin/env bash
# Redis RDB snapshot backup.
#
# Issues `BGSAVE` against the configured Redis, waits for completion, then
# copies the resulting `dump.rdb` (or AOF base file) to S3.
#
# Two execution modes:
#   * Path mode  — REDIS_DATA_DIR is mounted from the Redis server's data
#                  volume; we pick up `dump.rdb` directly.
#   * Network mode — REDIS_DATA_DIR is empty; we use `redis-cli --rdb` to
#                  stream a fresh RDB over the wire.
#
# Required env:
#   BACKUP_S3_BUCKET
#   REDIS_HOST
# Optional:
#   REDIS_PORT (6379)
#   REDIS_PASSWORD
#   REDIS_DATA_DIR
#   BACKUP_S3_PREFIX (redis)
#   BACKUP_RETENTION_DAYS (30)

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

tgai_install_error_trap "redis-backup"
tgai_require_env BACKUP_S3_BUCKET REDIS_HOST

REDIS_PORT="${REDIS_PORT:-6379}"
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-redis}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

redis_args=(-h "$REDIS_HOST" -p "$REDIS_PORT")
if [[ -n "${REDIS_PASSWORD:-}" ]]; then
    redis_args+=(-a "$REDIS_PASSWORD" --no-auth-warning)
fi

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
date_path="$(date -u +'%Y/%m/%d')"
host_safe="${REDIS_HOST//[^A-Za-z0-9_.-]/_}"
filename="${host_safe}-${timestamp}.rdb"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
local_path="$work_dir/$filename"

if [[ -n "${REDIS_DATA_DIR:-}" && -f "$REDIS_DATA_DIR/dump.rdb" ]]; then
    tgai_info "path mode: $REDIS_DATA_DIR/dump.rdb"

    last_save_pre="$(redis-cli "${redis_args[@]}" LASTSAVE)"
    tgai_info "issuing BGSAVE (LASTSAVE=$last_save_pre)"
    redis-cli "${redis_args[@]}" BGSAVE >/dev/null

    # Spin until LASTSAVE advances (BGSAVE finished).
    for _ in $(seq 1 120); do
        sleep 2
        cur="$(redis-cli "${redis_args[@]}" LASTSAVE || echo "$last_save_pre")"
        if [[ "$cur" != "$last_save_pre" ]]; then
            tgai_info "BGSAVE complete (LASTSAVE=$cur)"
            break
        fi
    done
    cp "$REDIS_DATA_DIR/dump.rdb" "$local_path"
else
    tgai_info "network mode: streaming RDB via redis-cli --rdb"
    redis-cli "${redis_args[@]}" --rdb "$local_path"
fi

bytes="$(stat -c '%s' "$local_path" 2>/dev/null || wc -c < "$local_path")"
tgai_info "RDB size: ${bytes} bytes"

min_bytes="${BACKUP_MIN_BYTES:-64}"
if (( bytes < min_bytes )); then
    tgai_die "RDB size ${bytes} < ${min_bytes} bytes — refusing to upload"
fi

sha256="$(sha256sum "$local_path" | awk '{print $1}')"
echo "$sha256  $filename" > "$local_path.sha256"

s3_key="${BACKUP_S3_PREFIX}/${date_path}/${filename}"
s3_url="s3://${BACKUP_S3_BUCKET}/${s3_key}"

tgai_s3_cp "$local_path" "$s3_url" \
    --metadata "sha256=${sha256},source-host=${REDIS_HOST},backup-type=rdb"
tgai_s3_cp "$local_path.sha256" "${s3_url}.sha256"

echo "$s3_key" > "$work_dir/latest"
tgai_s3_cp "$work_dir/latest" "s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}/latest" \
    --content-type text/plain

tgai_info "redis backup uploaded: $s3_url"

if [[ "${BACKUP_PRUNE_INLINE:-true}" == "true" ]]; then
    tgai_prune_prefix "s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}/" "$BACKUP_RETENTION_DAYS" || \
        tgai_warn "inline prune failed (non-fatal)"
fi

tgai_notify INFO "Redis backup OK" "host=${REDIS_HOST} size=${bytes}B key=${s3_key}"
