## Summary

On a 2xx upstream response with a missing/malformed body the verify/refresh routes write empty/garbage auth cookies and a session with no defined expiry.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | admin-dashboard |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`admin-dashboard/app/api/auth/login/verify/route.ts:26-37` reads `payload.access_token` etc. without validation and calls `persistTokens` (`lib/auth/cookies.ts:22-35`) with possibly `undefined` values → `store.set(name, undefined, { maxAge: undefined })`. Same pattern in `app/api/auth/refresh/route.ts:24-29`.

## Impact

A malformed-but-2xx upstream reply yields broken cookies and an access cookie with no `maxAge`, causing confusing downstream verification failures.

## Suggested fix

Validate the upstream payload with a zod schema (non-empty `access_token`/`refresh_token`, positive `expires_in`) before `persistTokens`; return 502 on mismatch.

## Acceptance criteria

- [ ] Malformed upstream payloads return 502 and do not set cookies.
- [ ] Persisted cookies always have a defined value and maxAge.
- [ ] Tests cover the malformed-payload path.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
