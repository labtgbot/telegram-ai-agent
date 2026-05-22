#!/usr/bin/env bash
# Shared helpers for backup / disaster-recovery scripts.
#
# Intentionally POSIX-ish bash so it runs on minimal alpine-based backup
# images (postgres:15-alpine, redis:7-alpine + bash, etc.). Every public
# function is prefixed `tgai_` so it does not collide with caller globals.

set -Eeuo pipefail

# --- Logging -----------------------------------------------------------------

tgai_log() {
    # tgai_log LEVEL "message..."
    local level="$1"
    shift
    printf '%s [%s] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$level" "$*" >&2
}

tgai_info()  { tgai_log INFO  "$@"; }
tgai_warn()  { tgai_log WARN  "$@"; }
tgai_error() { tgai_log ERROR "$@"; }

tgai_die() {
    tgai_error "$@"
    exit 1
}

# --- Required env ------------------------------------------------------------

tgai_require_env() {
    # tgai_require_env VAR1 VAR2 ...
    local missing=()
    local v
    for v in "$@"; do
        if [[ -z "${!v:-}" ]]; then
            missing+=("$v")
        fi
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        tgai_die "missing required env: ${missing[*]}"
    fi
}

# --- S3 (aws-cli wrapper) ---------------------------------------------------
#
# Supports both AWS S3 and S3-compatible providers (MinIO, R2, DO Spaces).
# Set BACKUP_S3_ENDPOINT to a non-empty URL to override the default endpoint.
# Encryption: if BACKUP_KMS_KEY_ID is set we pass --sse aws:kms --sse-kms-key-id;
# otherwise we fall back to SSE-S3 (AES256). Plaintext uploads are refused.

tgai_s3_args() {
    local args=()
    if [[ -n "${BACKUP_S3_ENDPOINT:-}" ]]; then
        args+=(--endpoint-url "$BACKUP_S3_ENDPOINT")
    fi
    if [[ -n "${BACKUP_S3_REGION:-}" ]]; then
        args+=(--region "$BACKUP_S3_REGION")
    fi
    printf '%s\n' "${args[@]}"
}

tgai_s3_sse_args() {
    local args=()
    if [[ -n "${BACKUP_KMS_KEY_ID:-}" ]]; then
        args+=(--sse aws:kms --sse-kms-key-id "$BACKUP_KMS_KEY_ID")
    else
        args+=(--sse AES256)
    fi
    printf '%s\n' "${args[@]}"
}

tgai_s3_cp() {
    # tgai_s3_cp SRC DST [extra aws s3 cp args]
    local src="$1" dst="$2"
    shift 2
    local -a global=() sse=()
    mapfile -t global < <(tgai_s3_args)
    mapfile -t sse < <(tgai_s3_sse_args)
    aws "${global[@]}" s3 cp "$src" "$dst" "${sse[@]}" "$@"
}

tgai_s3_sync() {
    # tgai_s3_sync SRC DST [extra args]
    local src="$1" dst="$2"
    shift 2
    local -a global=() sse=()
    mapfile -t global < <(tgai_s3_args)
    mapfile -t sse < <(tgai_s3_sse_args)
    aws "${global[@]}" s3 sync "$src" "$dst" "${sse[@]}" "$@"
}

tgai_s3_ls() {
    local -a global=()
    mapfile -t global < <(tgai_s3_args)
    aws "${global[@]}" s3 ls "$@"
}

tgai_s3_rm() {
    local -a global=()
    mapfile -t global < <(tgai_s3_args)
    aws "${global[@]}" s3 rm "$@"
}

# --- Retention ---------------------------------------------------------------

tgai_prune_prefix() {
    # tgai_prune_prefix s3://bucket/prefix/ RETENTION_DAYS
    #
    # Deletes objects under <prefix> whose LastModified is older than today
    # minus RETENTION_DAYS. Idempotent; safe to run repeatedly.
    local prefix="$1" days="$2"
    [[ "$days" =~ ^[0-9]+$ ]] || tgai_die "retention days must be a number: $days"
    local cutoff
    cutoff="$(date -u -d "${days} days ago" +%s 2>/dev/null \
        || python3 -c "import time,datetime as d; print(int((d.datetime.utcnow()-d.timedelta(days=${days})).timestamp()))")"
    tgai_info "pruning ${prefix} older than ${days} days (cutoff=${cutoff})"
    local listing
    listing="$(tgai_s3_ls "$prefix" --recursive || true)"
    if [[ -z "$listing" ]]; then
        tgai_info "nothing to prune"
        return 0
    fi
    local bucket
    bucket="$(awk -F/ '{print $3}' <<<"$prefix")"
    while IFS= read -r line; do
        # aws s3 ls --recursive output: "YYYY-MM-DD HH:MM:SS  SIZE  key"
        local ts key file_epoch full
        ts="$(awk '{print $1" "$2}' <<<"$line")"
        key="$(awk '{ for (i=4;i<=NF;i++) printf "%s%s", $i, (i<NF?" ":"\n") }' <<<"$line")"
        [[ -z "$key" ]] && continue
        file_epoch="$(date -u -d "$ts" +%s 2>/dev/null || echo 0)"
        if (( file_epoch > 0 && file_epoch < cutoff )); then
            full="$(printf 's3://%s/%s' "$bucket" "$key")"
            tgai_info "delete $full (modified $ts)"
            tgai_s3_rm "$full" || tgai_warn "failed to delete $full"
        fi
    done <<<"$listing"
}

# --- Notifications ------------------------------------------------------------

tgai_notify() {
    # tgai_notify LEVEL "subject" "body"
    #
    # No-op unless BACKUP_NOTIFY_WEBHOOK is set. The webhook receives a JSON
    # body compatible with both Slack incoming-webhooks and Mattermost.
    local level="$1" subject="$2" body="$3"
    if [[ -z "${BACKUP_NOTIFY_WEBHOOK:-}" ]]; then
        tgai_info "notify[$level]: $subject — $body"
        return 0
    fi
    local payload
    payload="$(printf '{"text":"*[%s] %s*\n%s"}' "$level" "$subject" "$body")"
    curl -fsS -m 10 -H 'Content-Type: application/json' \
        -d "$payload" "$BACKUP_NOTIFY_WEBHOOK" >/dev/null \
        || tgai_warn "notification webhook failed"
}

# --- Error trap --------------------------------------------------------------

tgai_install_error_trap() {
    # tgai_install_error_trap "context for alerts"
    local context="${1:-backup}"
    # shellcheck disable=SC2154  # rc is set as the trap's first statement
    trap '
        rc=$?
        tgai_error "FAILED ('"$context"') line $LINENO rc=$rc"
        tgai_notify ERROR "Backup failed: '"$context"'" "exit=$rc host=$(hostname) script=$0"
        exit $rc
    ' ERR
}
