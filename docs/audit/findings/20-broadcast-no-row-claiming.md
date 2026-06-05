## Summary

Due broadcasts and pending recipients are selected without `FOR UPDATE SKIP LOCKED` or an atomic claim, so two overlapping passes (the documented 30s cron, `--loop`, or two replicas) send the same recipient twice.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Medium |

## Evidence

`backend/app/services/broadcast.py:534-558` (`list_due_broadcasts`) and `:561-577` (`fetch_pending_recipients`) select without locking; `mark_broadcast_started` flips status only after selection. `backend/app/workers/broadcast.py:72-89` drives the drain.

## Impact

The same recipient can receive a broadcast twice and the combined send rate exceeds the intended `rate_limit`, risking Telegram 429/flood bans. The README suggests a 30s cron, making overlap realistic for large campaigns.

## Suggested fix

Claim recipients atomically (`UPDATE ... WHERE id IN (SELECT ... FOR UPDATE SKIP LOCKED LIMIT n)`) or guard the whole drain with `SELECT ... FOR UPDATE SKIP LOCKED` on the Broadcast row so only one worker drains a campaign.

## Acceptance criteria

- [ ] Overlapping worker passes never send a recipient twice.
- [ ] Concurrency test with two drains asserts exactly-once delivery per recipient.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
