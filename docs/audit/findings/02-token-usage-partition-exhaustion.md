## Summary

The partitioned `token_usage_logs` table is created with only two month partitions and no DEFAULT partition, and the monthly rotation job promised in the migration comment does not exist.

| | |
|---|---|
| **Severity** | CRITICAL |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 0 — Blocker (fix before any production deploy) |
| **Estimated complexity** | Medium |

## Evidence

`backend/alembic/versions/20260515_0001_baseline_initial_schema.py:142-194` creates the RANGE-partitioned parent plus only the current and next month partitions. The comment references a "ежемесячный Celery beat job" for rotation, but `backend/app/workers/` contains only `account_deletion, broadcast, daily_analytics, subscriptions, video_polling` — no partition manager (verified with grep for `PARTITION OF` / `CREATE TABLE token_usage_logs_`).

## Impact

`TokenUsageLog` is written on every billable action (`token_service.py:381`, `composio/usage.py:43`). Once `created_at` passes the end of the second pre-created month, every INSERT raises `no partition of relation "token_usage_logs" found for row`, breaking the core token-accounting / usage-logging path in production.

## Suggested fix

Ship a scheduled job (or migration-managed pg_partman) that pre-creates upcoming monthly partitions ahead of time, and add a `DEFAULT` partition as a safety net so inserts never hard-fail.

## Acceptance criteria

- [ ] A worker/cron pre-creates the next N monthly partitions and is covered by a test.
- [ ] A `DEFAULT` partition exists so an INSERT past the last partition still succeeds.
- [ ] An integration test inserts a row dated 3+ months out and it succeeds.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
