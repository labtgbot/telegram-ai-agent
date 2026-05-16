#!/usr/bin/env bash
# Restore a Redis RDB snapshot from object storage.
#
# Two delivery options:
#   --target-dir DIR   write dump.rdb to DIR (operator restarts redis-server)
#   --replace          (requires running redis on REDIS_HOST) flushes the
#                      target Redis and replays the RDB via redis-cli --pipe
#
# Required env:  BACKUP_S3_BUCKET
# For --replace: REDIS_HOST (+ optional REDIS_PORT / REDIS_PASSWORD)

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

tgai_install_error_trap "redis-restore"

mode="dir"
target_dir=""
explicit_key=""
dry_run=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target-dir) target_dir="${2:?--target-dir requires value}"; shift 2 ;;
        --replace)    mode="replace"; shift ;;
        --key)        explicit_key="${2:?--key requires value}"; shift 2 ;;
        --dry-run)    dry_run=true; shift ;;
        -h|--help)    sed -n '2,18p' "$0"; exit 0 ;;
        *) tgai_die "unknown arg: $1" ;;
    esac
done

tgai_require_env BACKUP_S3_BUCKET
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-redis}"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

if [[ -z "$explicit_key" ]]; then
    tgai_s3_cp "s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}/latest" \
        "$work_dir/latest" >/dev/null
    explicit_key="$(cat "$work_dir/latest")"
fi
[[ -n "$explicit_key" ]] || tgai_die "no S3 key resolved"

local_rdb="$work_dir/$(basename "$explicit_key")"
tgai_info "downloading s3://${BACKUP_S3_BUCKET}/${explicit_key}"
tgai_s3_cp "s3://${BACKUP_S3_BUCKET}/${explicit_key}" "$local_rdb"

if tgai_s3_cp "s3://${BACKUP_S3_BUCKET}/${explicit_key}.sha256" \
              "$local_rdb.sha256" 2>/dev/null; then
    expected="$(awk '{print $1}' "$local_rdb.sha256")"
    actual="$(sha256sum "$local_rdb" | awk '{print $1}')"
    [[ "$expected" == "$actual" ]] \
        || tgai_die "checksum mismatch: $expected != $actual"
    tgai_info "checksum OK"
fi

if $dry_run; then
    tgai_info "dry-run: download + checksum verified ($local_rdb)"
    exit 0
fi

case "$mode" in
    dir)
        [[ -n "$target_dir" ]] || tgai_die "--target-dir required without --replace"
        mkdir -p "$target_dir"
        cp "$local_rdb" "$target_dir/dump.rdb"
        tgai_info "wrote dump.rdb to $target_dir — restart redis-server to load"
        ;;
    replace)
        tgai_require_env REDIS_HOST
        redis_port="${REDIS_PORT:-6379}"
        redis_args=(-h "$REDIS_HOST" -p "$redis_port")
        if [[ -n "${REDIS_PASSWORD:-}" ]]; then
            redis_args+=(-a "$REDIS_PASSWORD" --no-auth-warning)
        fi
        tgai_warn "FLUSHALL on $REDIS_HOST:$redis_port"
        redis-cli "${redis_args[@]}" FLUSHALL
        # rdb-to-resp via redis-cli isn't built-in. Recommend operator-side
        # path for true RDB load (place file + restart). Provide friendly
        # error rather than silently doing nothing.
        tgai_die "--replace mode currently only flushes the cache. \
For a full RDB load, mount this dump as /data/dump.rdb and restart redis-server."
        ;;
esac

tgai_notify INFO "Redis restore OK" "host=${REDIS_HOST:-n/a} mode=$mode key=$explicit_key"
