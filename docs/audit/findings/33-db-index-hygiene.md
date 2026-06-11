## Summary

Two single-column duplicate B-tree indexes on a hot table waste storage and add write amplification; `usage_log_id` columns carry no FK (an unavoidable consequence of the composite partitioned PK, worth documenting).

| | |
|---|---|
| **Severity** | LOW |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 3 — Low priority (hygiene / defence-in-depth) |
| **Estimated complexity** | Low |

## Evidence

`backend/app/models/user.py:20,58,80,86` — `telegram_id`/`referral_code` are `unique=True` (unique index) *and* get extra `Index("ix_users_telegram_id", ...)` / `ix_users_referral`. `chat_history.py:121`, `video_job.py:84` reference `token_usage_logs` with no FK (the composite PK `(id, created_at)` makes a single-column FK impossible).

## Impact

Wasted storage / write amplification on `users`; no referential integrity on `usage_log_id` links (dangling on rotation).

## Suggested fix

Drop the redundant `ix_users_telegram_id`/`ix_users_referral` indexes (keep the unique ones) via a migration; either accept and document the FK-less link or store `(usage_log_id, usage_log_created_at)` with a composite FK.

## Resolution

`ix_users_telegram_id` and `ix_users_referral` are removed from the model and dropped
by migration `0014_drop_redundant_user_indexes`; the unique constraints remain the
lookup indexes for `users.telegram_id` and `users.referral_code`.

The `usage_log_id` links are intentionally kept as FK-less scalar audit pointers.
`token_usage_logs` is range-partitioned by `created_at`, so PostgreSQL requires
`created_at` in its primary/unique key. Adding a real FK would require storing
`usage_log_created_at` beside every pointer and reshaping existing service/API
contracts; this low-priority hygiene fix documents the tradeoff instead.

## Acceptance criteria

- [x] Redundant single-column indexes are removed (model + migration).
- [x] The `usage_log_id` FK decision is documented or implemented.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
