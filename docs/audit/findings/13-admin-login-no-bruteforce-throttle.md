## Summary

The admin login `request` endpoint has no rate limit and re-issuing a code resets the verify attempt counter, so the 6-digit code can be brute-forced over time.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Medium |

## Evidence

`backend/app/api/v1/auth.py:168-197` (request) has no rate-limit dependency and each call deletes the attempts key (`admin_login.py:101`), resetting the 5-attempt budget in `verify_admin_login` (`admin_login.py:124-129`). Neither `/auth/admin/login/request` nor `/auth/admin/login/verify` is IP/identity throttled.

## Impact

An attacker can repeatedly re-request to reset the attempt budget and brute force the 1e6-space code, and flood the admin via the bot with code messages.

## Suggested fix

Add IP- and telegram_id-scoped rate limits to both endpoints, and make the attempt counter independent of code re-issuance (or cap re-requests per window).

## Acceptance criteria

- [ ] Both admin-login endpoints are rate limited per IP and per telegram_id.
- [ ] Re-requesting a code does not reset the brute-force attempt budget.
- [ ] Tests cover lockout after N failed verifications across re-requests.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
