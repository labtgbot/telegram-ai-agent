## Summary

The account-deletion worker processes all due deletions in one shared session/transaction; a single failing item poisons the session, discards already-completed anonymisations, and never persists the FAILED status.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Medium |

## Evidence

`backend/app/workers/account_deletion.py:44-68` runs the loop on one `session` with a single `commit()` after the loop. The per-item `except` (`:56-63`) sets `request.status = FAILED` on the *same* session that already raised; once `anonymise_user` fails mid-way (e.g. one of the `delete(...)`/`update` in `account_deletion.py:259-271` errors) the session is in `PendingRollbackError` state, so the FAILED assignment and the final `commit()` raise and the outer `except` rolls back the entire pass.

## Impact

A single problematic user blocks GDPR Art. 17 anonymisation for the whole batch (data that must be erased remains) and the FAILED status is never recorded, so the poison row blocks every subsequent run too.

## Suggested fix

Give each request its own transaction (commit per item, or `session.begin_nested()` savepoints) and `rollback()` inside the per-item `except` before flipping that single request to FAILED and committing it, so one failure cannot revert siblings.

## Acceptance criteria

- [ ] A failing deletion isolates to that request; siblings still complete and commit.
- [ ] A failed deletion is persisted with FAILED status and an error reason.
- [ ] A poison row does not block subsequent worker runs (test with a forced failure).

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
