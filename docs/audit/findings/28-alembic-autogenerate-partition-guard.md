## Summary

`env.py` enables `compare_type`/`compare_server_default` but has no `include_object` filter, so autogenerate sees live partition child tables as unknown and would emit `drop_table` directives for the partitioned table.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | MEDIUM |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`backend/alembic/env.py:62-68` (and offline `:45-59`) — no `include_object`/`include_name` and no `process_revision_directives`. SQLAlchemy autogenerate doesn't understand `postgresql_partition_by` or `token_usage_logs_YYYY_MM` children.

## Impact

A future `--autogenerate` may produce `op.drop_table("token_usage_logs_2026_05")` and re-create directives, risking data loss if applied blindly.

## Suggested fix

Add an `include_object`/`include_name` callback that skips partition child tables and the partitioned parent.

## Acceptance criteria

- [ ] `--autogenerate` ignores partition-managed objects.
- [ ] A test or documented check confirms no spurious drop directives for partitions.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
