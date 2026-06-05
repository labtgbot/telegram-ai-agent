## Summary

The normal one-time Stars purchase path credits the balance in-place and flushes, but never refreshes the Redis balance cache, so the user keeps seeing their pre-purchase balance until the TTL expires.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Low |

## Evidence

`backend/app/services/payments.py:441-475` — the `pending is not None and not is_recurring` branch mutates `user.token_balance` directly and `flush()`es but never calls `token_service._refresh_cache(...)`. The `else` branch (`token_service.add`) does refresh (`token_service.py:317`). `get_balance` (`token_service.py:182-185`) returns the cached value first.

## Impact

After a normal purchase the cached (lower) balance is served until `balance_cache_ttl_seconds`, so a user who just paid may be wrongly told they have insufficient tokens. The DB is correct; the cache lies until TTL or the next `TokenService` mutation.

## Suggested fix

After the in-place credit + flush, call `await token_service._refresh_cache(user.id, int(user.token_balance))`, or route the credit through `TokenService.add` consistently with the `else` branch.

## Acceptance criteria

- [ ] The Redis balance cache reflects the new balance immediately after a Stars purchase.
- [ ] A regression test asserts the cached balance equals the DB balance post-purchase.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
