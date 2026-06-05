## Summary

The webhook never records/checks `update_id`, so a Telegram redelivery (slow handler, pod restart, network error on the response) reprocesses the update and fires non-idempotent side effects again.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | MEDIUM |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Medium |

## Evidence

`backend/app/api/v1/bot.py:94-114` logs but does not dedupe `update_id`; `dispatcher.py:45-92` reprocesses from scratch. `/bonus` and `successful_payment` are guarded, but `/start` referral crediting, `/image`/`/video`/`/ask` (token spend + provider cost) and broadcast click counting are not; the per-call `request_id` is fresh on redelivery.

## Impact

Redelivered updates can double-credit referrals, double-spend tokens and incur duplicate provider cost.

## Suggested fix

Persist processed `update_id`s (Redis SETNX with TTL, or a unique table) and short-circuit duplicates before dispatch, returning 200 without re-running side effects.

## Acceptance criteria

- [ ] A redelivered `update_id` is processed at most once.
- [ ] Test posts the same update twice and asserts side effects fire once.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
