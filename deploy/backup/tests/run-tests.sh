#!/usr/bin/env bash
# Unit tests for deploy/backup/scripts/lib/common.sh.
#
# Goals:
#   * No network. We stub `aws` and `curl` on PATH so every helper that wraps
#     them becomes observable.
#   * Run on plain bash 5.x — no bats / external runners required so it can
#     execute inside the same Alpine image we ship.
#
# Each test is a function `test_<name>`; the runner calls every function
# whose name starts with `test_` in declaration order.

set -Eeuo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../scripts" && pwd)"

# --- Stub harness ----------------------------------------------------------

STUB_DIR="$(mktemp -d)"
export STUB_DIR
export STUB_LOG="$STUB_DIR/calls.log"
: > "$STUB_LOG"

trap 'rm -rf "$STUB_DIR"' EXIT

cat > "$STUB_DIR/aws" <<'EOF'
#!/usr/bin/env bash
# Record invocation + emit canned output if STUB_AWS_OUT is set.
printf 'aws %s\n' "$*" >> "$STUB_LOG"
if [[ -n "${STUB_AWS_OUT:-}" ]]; then
    printf '%s\n' "$STUB_AWS_OUT"
fi
exit "${STUB_AWS_RC:-0}"
EOF
chmod +x "$STUB_DIR/aws"

cat > "$STUB_DIR/curl" <<'EOF'
#!/usr/bin/env bash
printf 'curl %s\n' "$*" >> "$STUB_LOG"
exit "${STUB_CURL_RC:-0}"
EOF
chmod +x "$STUB_DIR/curl"

export PATH="$STUB_DIR:$PATH"

# Source the unit under test. Disable the `set -e` propagation while sourcing
# so that helpers that intentionally fail (tgai_die) don't kill the runner.
# shellcheck disable=SC1091
source "$ROOT/lib/common.sh"

# --- Assertions ------------------------------------------------------------

PASS=0
FAIL=0
FAILED_NAMES=()

assert_eq() {
    local expected="$1" actual="$2" msg="${3:-values}"
    if [[ "$expected" != "$actual" ]]; then
        printf '  FAIL: %s\n    expected: %q\n    actual:   %q\n' \
            "$msg" "$expected" "$actual" >&2
        return 1
    fi
}

assert_contains() {
    local haystack="$1" needle="$2" msg="${3:-substring}"
    if [[ "$haystack" != *"$needle"* ]]; then
        printf '  FAIL: %s\n    haystack: %s\n    needle:   %q\n' \
            "$msg" "$haystack" "$needle" >&2
        return 1
    fi
}

# Wrap each test so failures are reported but don't abort the suite.
run_test() {
    local name="$1"
    local out rc=0
    # Reset stubs between tests
    : > "$STUB_LOG"
    unset STUB_AWS_OUT STUB_AWS_RC STUB_CURL_RC
    out="$("$name" 2>&1)" || rc=$?
    if (( rc == 0 )); then
        printf 'ok   %s\n' "$name"
        PASS=$((PASS + 1))
    else
        printf 'FAIL %s (rc=%d)\n%s\n' "$name" "$rc" "$out" >&2
        FAIL=$((FAIL + 1))
        FAILED_NAMES+=("$name")
    fi
}

# --- Tests -----------------------------------------------------------------

test_require_env_passes_when_set() {
    FOO=bar tgai_require_env FOO
}

test_require_env_dies_when_missing() {
    local rc=0
    ( unset MISSING_VAR; tgai_require_env MISSING_VAR ) >/dev/null 2>&1 || rc=$?
    if (( rc == 0 )); then
        echo "expected non-zero exit, got 0" >&2
        return 1
    fi
}

test_s3_args_empty_by_default() {
    unset BACKUP_S3_ENDPOINT BACKUP_S3_REGION
    local out
    out="$(tgai_s3_args | tr -d '\n')"
    assert_eq "" "$out" "tgai_s3_args with no env should be empty"
}

test_s3_args_includes_endpoint_and_region() {
    BACKUP_S3_ENDPOINT="https://s3.example" \
    BACKUP_S3_REGION="eu-central-1" \
        bash -c '
            set -Eeuo pipefail
            source "$1"
            tgai_s3_args
        ' _ "$ROOT/lib/common.sh" > /tmp/s3args.$$
    local content
    content="$(tr '\n' ' ' < /tmp/s3args.$$)"
    rm -f /tmp/s3args.$$
    assert_contains "$content" "--endpoint-url https://s3.example"
    assert_contains "$content" "--region eu-central-1"
}

test_s3_sse_args_defaults_to_aes256() {
    unset BACKUP_KMS_KEY_ID
    local content
    content="$(tgai_s3_sse_args | tr '\n' ' ')"
    assert_contains "$content" "--sse AES256" "default SSE should be AES256"
    [[ "$content" != *"aws:kms"* ]] || {
        echo "default SSE should not be KMS"; return 1;
    }
}

test_s3_sse_args_uses_kms_when_set() {
    BACKUP_KMS_KEY_ID="arn:aws:kms:eu-central-1:1234:key/abcd" \
        bash -c '
            set -Eeuo pipefail
            source "$1"
            tgai_s3_sse_args
        ' _ "$ROOT/lib/common.sh" > /tmp/sse.$$
    local content
    content="$(tr '\n' ' ' < /tmp/sse.$$)"
    rm -f /tmp/sse.$$
    assert_contains "$content" "--sse aws:kms"
    assert_contains "$content" "--sse-kms-key-id arn:aws:kms:eu-central-1:1234:key/abcd"
}

test_s3_cp_invokes_aws_with_sse() {
    unset BACKUP_S3_ENDPOINT BACKUP_S3_REGION BACKUP_KMS_KEY_ID
    tgai_s3_cp /tmp/x s3://bucket/key >/dev/null
    grep -q 's3 cp /tmp/x s3://bucket/key --sse AES256' "$STUB_LOG" \
        || { cat "$STUB_LOG" >&2; return 1; }
}

test_s3_cp_uses_kms_when_set() {
    unset BACKUP_S3_ENDPOINT BACKUP_S3_REGION
    BACKUP_KMS_KEY_ID="arn:aws:kms:eu-central-1:1234:key/abcd" \
        tgai_s3_cp /tmp/x s3://bucket/key >/dev/null
    grep -q 'aws:kms' "$STUB_LOG" || { cat "$STUB_LOG" >&2; return 1; }
    grep -q "arn:aws:kms:eu-central-1:1234:key/abcd" "$STUB_LOG" \
        || { cat "$STUB_LOG" >&2; return 1; }
    # Must never fall through to AES256 when KMS is configured.
    if grep -q -- '--sse AES256' "$STUB_LOG"; then
        echo "AES256 should not appear when KMS is configured" >&2
        cat "$STUB_LOG" >&2
        return 1
    fi
}

test_prune_rejects_non_numeric_days() {
    # tgai_die calls `exit 1`; run in a subshell so it doesn't kill the suite.
    local rc=0
    ( tgai_prune_prefix s3://bucket/prefix/ "thirty" ) >/dev/null 2>&1 || rc=$?
    if (( rc == 0 )); then
        echo "expected non-zero exit for non-numeric days, got 0" >&2
        return 1
    fi
}

test_prune_noop_when_empty_listing() {
    # run_test already clears STUB_AWS_OUT, so listing is empty by default.
    tgai_prune_prefix s3://bucket/prefix/ 30 >/dev/null
    if grep -q ' s3 rm ' "$STUB_LOG"; then
        echo "expected no rm calls for empty listing" >&2
        cat "$STUB_LOG" >&2
        return 1
    fi
}

test_notify_logs_when_no_webhook() {
    unset BACKUP_NOTIFY_WEBHOOK
    local out
    out="$(tgai_notify INFO subj body 2>&1)"
    assert_contains "$out" "notify[INFO]"
}

test_notify_calls_webhook_when_set() {
    BACKUP_NOTIFY_WEBHOOK="https://hooks.example/x" \
        tgai_notify WARN subj body >/dev/null 2>&1
    grep -q '^curl' "$STUB_LOG" || { cat "$STUB_LOG" >&2; return 1; }
    grep -q 'https://hooks.example/x' "$STUB_LOG" \
        || { cat "$STUB_LOG" >&2; return 1; }
}

test_log_format_includes_timestamp() {
    local out
    out="$(tgai_info "hello world" 2>&1)"
    # ISO-8601 timestamp prefix
    assert_contains "$out" "[INFO]"
    assert_contains "$out" "hello world"
    [[ "$out" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T ]] || {
        echo "expected ISO-8601 timestamp prefix, got: $out" >&2
        return 1
    }
}

# --- Smoke: every script parses without syntax errors ----------------------

test_scripts_pass_bash_n() {
    local f
    for f in "$ROOT"/*.sh "$ROOT"/lib/*.sh; do
        bash -n "$f" || { echo "syntax error in $f" >&2; return 1; }
    done
}

# --- Runner ----------------------------------------------------------------

main() {
    local fn
    while read -r fn; do
        run_test "$fn"
    done < <(declare -F | awk '{print $3}' | grep '^test_')

    printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
    if (( FAIL > 0 )); then
        printf 'failed: %s\n' "${FAILED_NAMES[*]}"
        exit 1
    fi
}

main "$@"
