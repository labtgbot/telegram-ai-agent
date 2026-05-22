#!/usr/bin/env bash
# Daily full PostgreSQL backup.
#
# Produces a custom-format pg_dump of $POSTGRES_DB and uploads it to
# s3://$BACKUP_S3_BUCKET/postgres/full/YYYY/MM/DD/<host>-<db>-<timestamp>.dump.
# Encryption is enforced via lib/common.sh (KMS or SSE-S3).
#
# Required env:
#   PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE
#   BACKUP_S3_BUCKET
# Optional:
#   BACKUP_S3_PREFIX        (default "postgres")
#   BACKUP_S3_REGION
#   BACKUP_S3_ENDPOINT
#   BACKUP_KMS_KEY_ID
#   BACKUP_RETENTION_DAYS   (default 30 — controls prune step)
#   PG_DUMP_EXTRA_ARGS      (extra args appended to pg_dump)

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

tgai_install_error_trap "postgres-backup"

tgai_require_env PGHOST PGUSER PGPASSWORD PGDATABASE BACKUP_S3_BUCKET

PGPORT="${PGPORT:-5432}"
BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-postgres}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

timestamp="$(date -u +'%Y%m%dT%H%M%SZ')"
date_path="$(date -u +'%Y/%m/%d')"
host_safe="${PGHOST//[^A-Za-z0-9_.-]/_}"
filename="${host_safe}-${PGDATABASE}-${timestamp}.dump"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
local_path="$work_dir/$filename"

tgai_info "starting pg_dump host=$PGHOST db=$PGDATABASE -> $filename"

# Custom format (-Fc) is portable + parallel-restorable.
# --no-owner / --no-privileges keep restore database-agnostic.
# shellcheck disable=SC2086
pg_dump \
    --host "$PGHOST" \
    --port "$PGPORT" \
    --username "$PGUSER" \
    --dbname "$PGDATABASE" \
    --format=custom \
    --compress=6 \
    --no-owner \
    --no-privileges \
    --verbose \
    ${PG_DUMP_EXTRA_ARGS:-} \
    --file "$local_path" 2> "$work_dir/pg_dump.log" || {
        tgai_error "pg_dump failed; see log:"
        cat "$work_dir/pg_dump.log" >&2 || true
        exit 1
    }

bytes="$(stat -c '%s' "$local_path" 2>/dev/null || wc -c < "$local_path")"
tgai_info "pg_dump produced ${bytes} bytes"

# Refuse to upload a suspiciously small dump (likely empty schema → corrupt).
min_bytes="${BACKUP_MIN_BYTES:-1024}"
if (( bytes < min_bytes )); then
    tgai_die "dump size ${bytes} < ${min_bytes} bytes — refusing to upload"
fi

# Optional checksum for the catalog manifest.
sha256="$(sha256sum "$local_path" | awk '{print $1}')"
echo "$sha256  $filename" > "$local_path.sha256"

s3_key="${BACKUP_S3_PREFIX}/full/${date_path}/${filename}"
s3_url="s3://${BACKUP_S3_BUCKET}/${s3_key}"

tgai_info "uploading $s3_url"
tgai_s3_cp "$local_path" "$s3_url" \
    --metadata "sha256=${sha256},source-host=${PGHOST},database=${PGDATABASE},backup-type=full"
tgai_s3_cp "$local_path.sha256" "${s3_url}.sha256"

# Maintain a "latest" pointer so restore drills don't have to grep listings.
echo "$s3_key" > "$work_dir/latest"
tgai_s3_cp "$work_dir/latest" "s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}/full/latest" \
    --content-type text/plain

tgai_info "upload OK ($s3_url)"

# Retention — best-effort. A separate prune CronJob is the canonical owner;
# this in-line prune just catches drift between runs.
if [[ "${BACKUP_PRUNE_INLINE:-true}" == "true" ]]; then
    tgai_prune_prefix "s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}/full/" "$BACKUP_RETENTION_DAYS" || \
        tgai_warn "inline prune failed (non-fatal)"
fi

tgai_notify INFO "Postgres backup OK" "host=${PGHOST} db=${PGDATABASE} size=${bytes}B key=${s3_key}"
