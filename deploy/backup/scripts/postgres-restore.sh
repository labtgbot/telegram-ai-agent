#!/usr/bin/env bash
# Restore a PostgreSQL dump from object storage.
#
# Two modes:
#   --latest                   restore the file pointed to by "<prefix>/full/latest"
#   --key <s3-key>             restore an explicit object
#
# Target is configured via env (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE)
# and a small set of flags:
#   --dry-run                  download and verify checksum; do NOT touch DB
#   --drop                     drop+recreate the target database first
#   --jobs N                   pg_restore --jobs (default 4)
#
# Required env:
#   BACKUP_S3_BUCKET
#   PGHOST PGUSER PGPASSWORD PGDATABASE
# Optional env:
#   BACKUP_S3_PREFIX (default postgres)
#   BACKUP_S3_REGION / BACKUP_S3_ENDPOINT

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

tgai_install_error_trap "postgres-restore"

mode="latest"
explicit_key=""
dry_run=false
drop_db=false
jobs=4

while [[ $# -gt 0 ]]; do
    case "$1" in
        --latest)   mode="latest"; shift ;;
        --key)      mode="explicit"; explicit_key="${2:?--key requires value}"; shift 2 ;;
        --dry-run)  dry_run=true; shift ;;
        --drop)     drop_db=true; shift ;;
        --jobs)     jobs="${2:?--jobs requires value}"; shift 2 ;;
        -h|--help)
            sed -n '2,20p' "$0"
            exit 0
            ;;
        *) tgai_die "unknown arg: $1" ;;
    esac
done

tgai_require_env BACKUP_S3_BUCKET
$dry_run || tgai_require_env PGHOST PGUSER PGPASSWORD PGDATABASE
PGPORT="${PGPORT:-5432}"
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-postgres}"

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

if [[ "$mode" == "latest" ]]; then
    tgai_info "resolving latest pointer"
    tgai_s3_cp "s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}/full/latest" \
        "$work_dir/latest" >/dev/null
    explicit_key="$(cat "$work_dir/latest")"
fi
[[ -n "$explicit_key" ]] || tgai_die "no S3 key resolved"

local_dump="$work_dir/$(basename "$explicit_key")"
tgai_info "downloading s3://${BACKUP_S3_BUCKET}/${explicit_key}"
tgai_s3_cp "s3://${BACKUP_S3_BUCKET}/${explicit_key}" "$local_dump"

# Verify checksum if a sidecar exists.
checksum_url="s3://${BACKUP_S3_BUCKET}/${explicit_key}.sha256"
if tgai_s3_cp "$checksum_url" "$local_dump.sha256" 2>/dev/null; then
    tgai_info "verifying SHA-256"
    expected="$(awk '{print $1}' "$local_dump.sha256")"
    actual="$(sha256sum "$local_dump" | awk '{print $1}')"
    [[ "$expected" == "$actual" ]] \
        || tgai_die "checksum mismatch: expected=$expected actual=$actual"
    tgai_info "checksum OK ($actual)"
else
    tgai_warn "no checksum sidecar found — skipping verification"
fi

if $dry_run; then
    tgai_info "dry-run: file is valid and downloaded ($local_dump)"
    pg_restore --list "$local_dump" >/dev/null
    tgai_info "pg_restore --list parsed the dump TOC successfully"
    exit 0
fi

if $drop_db; then
    tgai_warn "dropping and recreating database $PGDATABASE on $PGHOST"
    PGDATABASE_ADMIN="${PGDATABASE_ADMIN:-postgres}"
    psql --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" \
        --dbname "$PGDATABASE_ADMIN" \
        --set ON_ERROR_STOP=on \
        -c "DROP DATABASE IF EXISTS \"$PGDATABASE\";" \
        -c "CREATE DATABASE \"$PGDATABASE\";"
fi

tgai_info "running pg_restore --jobs=$jobs into $PGDATABASE@$PGHOST"
pg_restore \
    --host "$PGHOST" \
    --port "$PGPORT" \
    --username "$PGUSER" \
    --dbname "$PGDATABASE" \
    --jobs "$jobs" \
    --no-owner \
    --no-privileges \
    --exit-on-error \
    --verbose \
    "$local_dump"

tgai_info "restore complete"
tgai_notify INFO "Postgres restore OK" "host=$PGHOST db=$PGDATABASE key=$explicit_key"
