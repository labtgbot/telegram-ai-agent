#!/usr/bin/env bash
# Archive a single WAL segment to object storage.
#
# Intended to be wired into Postgres `archive_command`:
#
#   archive_command = 'PGUSER=postgres BACKUP_S3_BUCKET=... \
#       /opt/tgai/postgres-wal-archive.sh %p %f'
#
# %p — path to the WAL file inside pg_wal
# %f — bare filename of the WAL segment
#
# The script writes to
#   s3://$BACKUP_S3_BUCKET/$BACKUP_S3_PREFIX/wal/<filename>
# and exits non-zero on failure so Postgres retries.

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

tgai_install_error_trap "postgres-wal-archive"
tgai_require_env BACKUP_S3_BUCKET

BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-postgres}"
src="${1:?missing %p — WAL source path}"
name="${2:?missing %f — WAL filename}"

[[ -r "$src" ]] || tgai_die "WAL source not readable: $src"

dest="s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}/wal/${name}"

# WAL segments are 16 MiB each by default. Multi-part is overkill — single cp.
tgai_s3_cp "$src" "$dest" --metadata "wal-segment=${name}"

# Light-touch ack — Postgres rotates archive_command very fast in busy DBs;
# only log at DEBUG-equivalent volume to avoid spamming logs.
if [[ "${WAL_ARCHIVE_VERBOSE:-false}" == "true" ]]; then
    tgai_info "archived WAL $name -> $dest"
fi
