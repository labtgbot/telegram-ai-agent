#!/usr/bin/env bash
# Cross-region / cross-bucket media backup.
#
# The application media bucket ($MEDIA_S3_BUCKET) is treated as the source of
# truth. This script mirrors it to a separate backup bucket using `aws s3
# sync` with object versioning enabled on the destination (set up by the
# bucket administrator, not by this script — see docs/BACKUP_RECOVERY.md).
#
# Required env:
#   MEDIA_S3_BUCKET           source bucket (application bucket)
#   BACKUP_S3_BUCKET          destination bucket (cold storage)
# Optional:
#   MEDIA_S3_PREFIX           subprefix on the source (default empty = root)
#   BACKUP_S3_PREFIX          destination prefix (default "media")
#   BACKUP_S3_ENDPOINT        used for BOTH buckets if both providers match;
#                             leave empty when crossing providers
#   BACKUP_KMS_KEY_ID         KMS key on destination bucket
#   MEDIA_SYNC_DELETE         when "true", mirror deletions (default "false")

set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=SCRIPTDIR/lib/common.sh
. "$SCRIPT_DIR/lib/common.sh"

tgai_install_error_trap "media-sync"
tgai_require_env MEDIA_S3_BUCKET BACKUP_S3_BUCKET

BACKUP_S3_PREFIX="${BACKUP_S3_PREFIX:-media}"
MEDIA_S3_PREFIX="${MEDIA_S3_PREFIX:-}"
delete_flag=()
if [[ "${MEDIA_SYNC_DELETE:-false}" == "true" ]]; then
    delete_flag+=(--delete)
fi

src="s3://${MEDIA_S3_BUCKET}"
[[ -n "$MEDIA_S3_PREFIX" ]] && src="${src}/${MEDIA_S3_PREFIX}"
dst="s3://${BACKUP_S3_BUCKET}/${BACKUP_S3_PREFIX}"

tgai_info "media sync: $src -> $dst (delete=${MEDIA_SYNC_DELETE:-false})"
tgai_s3_sync "$src" "$dst" "${delete_flag[@]}" --only-show-errors
tgai_info "media sync complete"

tgai_notify INFO "Media sync OK" "src=$src dst=$dst"
