## Summary

A racing double-tap of the daily-bonus claim can trip the transactions unique index inside `token_service.add` (before the guarded claim insert), surfacing an unhandled 500 and aborting the session.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`backend/app/services/daily_bonus.py:333-363` — the surrounding `try` only catches `UserNotFoundError`; `token_service.add` flushes a `Transaction` with a deterministic `payment_id` (`daily_bonus:user:{id}:date:...`) guarded by `uq_transactions_payment_id`. Only the later `DailyBonusClaim` insert is wrapped in `except IntegrityError`.

## Impact

No double-credit (the unique index prevents it — a correctness win) but a concurrent claim returns 500 instead of a clean `AlreadyClaimedError`, and the aborted transaction can break the rest of the request.

## Suggested fix

Wrap the `token_service.add` call in `except IntegrityError` (rollback → `AlreadyClaimedError`) or use a `begin_nested()` savepoint, mirroring `payments._maybe_credit_referral_bonus`.

## Acceptance criteria

- [ ] A concurrent second claim returns the clean AlreadyClaimed response, not 500.
- [ ] The session remains usable after the race.
- [ ] A concurrency test reproduces the race and asserts the fix.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
