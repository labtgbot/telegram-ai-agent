## Summary

`spend`/`add`/`refund` write the new balance to Redis immediately after `flush()` but before the caller commits, so an outer rollback leaves a stale value cached until TTL.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | MEDIUM |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Medium |

## Evidence

`backend/app/services/token_service.py:237-257` (`_refresh_cache`), called at `:317,394,531` right after `flush()` but before the request commits. `get_balance` serves that value.

## Impact

If the owning transaction later rolls back, Redis retains a value that was never committed (higher or lower than truth) until TTL, causing wrongful insufficient-tokens rejections or transient over-statement.

## Suggested fix

Invalidate (delete) the cache key on mutation instead of writing pre-commit, or move the write-through to an after-commit hook so Redis only reflects committed state.

## Acceptance criteria

- [ ] The cache never reflects an uncommitted/rolled-back balance.
- [ ] A test that rolls back after a spend asserts the cached balance matches the committed DB value.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
