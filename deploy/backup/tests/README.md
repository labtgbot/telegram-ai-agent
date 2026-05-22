# Backup script tests

Unit tests for the helpers in `deploy/backup/scripts/lib/common.sh` and
smoke-tests for the top-level scripts.

```bash
# Run locally:
bash deploy/backup/tests/run-tests.sh

# Optional: shellcheck pass over every script:
shellcheck deploy/backup/scripts/*.sh deploy/backup/scripts/lib/*.sh \
    deploy/backup/tests/run-tests.sh
```

The harness avoids hitting any real network — it stubs `aws` and `curl` on
`PATH` so calls into S3 / webhooks become deterministic recordings.

CI exercises this from `.github/workflows/deploy.yml`
(`backup-scripts-test` job).
