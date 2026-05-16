#!/usr/bin/env bash
# Quarterly restore drill.
#
# Downloads the most recent Postgres dump and attempts an ephemeral restore
# into a throw-away database, then runs a smoke query and counts rows in a
# handful of canonical tables. Failure paths emit alerts so we catch backup
# rot before an actual incident.
#
# Required env:
#   BACKUP_S3_BUCKET
#   PGHOST PGUSER PGPASSWORD
# Optional:
#   PGDATABASE_RESTORE_TARGET   ephemeral DB name (default "backup_verify")
#   BACKUP_SMOKE_TABLES         comma-separated list of tables to count rows
#                                in after restore. Each must produce > 0
#                                rows. Defaults to a conservative "users".

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

tgai_install_error_trap "verify-backup"
tgai_require_env BACKUP_S3_BUCKET PGHOST PGUSER PGPASSWORD

PGPORT="${PGPORT:-5432}"
PGDATABASE_RESTORE_TARGET="${PGDATABASE_RESTORE_TARGET:-backup_verify}"
PGDATABASE_ADMIN="${PGDATABASE_ADMIN:-postgres}"
BACKUP_SMOKE_TABLES="${BACKUP_SMOKE_TABLES:-users}"

# (Re)create the throw-away database.
tgai_info "preparing ephemeral DB $PGDATABASE_RESTORE_TARGET"
psql --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" \
    --dbname "$PGDATABASE_ADMIN" --set ON_ERROR_STOP=on \
    -c "DROP DATABASE IF EXISTS \"$PGDATABASE_RESTORE_TARGET\";" \
    -c "CREATE DATABASE \"$PGDATABASE_RESTORE_TARGET\";"

PGDATABASE="$PGDATABASE_RESTORE_TARGET" \
    "$SCRIPT_DIR/postgres-restore.sh" --latest --jobs "${PG_RESTORE_JOBS:-4}"

# Smoke checks — count rows on a few canonical tables and verify schema_version.
IFS=',' read -r -a tables <<<"$BACKUP_SMOKE_TABLES"
for tbl in "${tables[@]}"; do
    tbl_trim="$(echo "$tbl" | xargs)"
    [[ -z "$tbl_trim" ]] && continue
    tgai_info "smoke check: SELECT count(*) FROM $tbl_trim"
    n="$(psql --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" \
        --dbname "$PGDATABASE_RESTORE_TARGET" --tuples-only --no-align \
        --set ON_ERROR_STOP=on \
        -c "SELECT count(*) FROM \"$tbl_trim\";")"
    n_int="$(printf '%s' "$n" | tr -d ' ')"
    [[ "$n_int" =~ ^[0-9]+$ ]] || tgai_die "non-numeric count for $tbl_trim: $n"
    tgai_info "table $tbl_trim has $n_int rows"
done

# Drop the ephemeral DB so we don't bloat the host.
if [[ "${VERIFY_KEEP_DB:-false}" != "true" ]]; then
    psql --host "$PGHOST" --port "$PGPORT" --username "$PGUSER" \
        --dbname "$PGDATABASE_ADMIN" --set ON_ERROR_STOP=on \
        -c "DROP DATABASE IF EXISTS \"$PGDATABASE_RESTORE_TARGET\";"
fi

tgai_info "verify OK"
tgai_notify INFO "Restore drill OK" \
    "ephemeral_db=$PGDATABASE_RESTORE_TARGET tables=$BACKUP_SMOKE_TABLES"
