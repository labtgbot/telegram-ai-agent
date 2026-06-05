## Summary

Three low-severity auth hardening items: a non-constant-time webhook-secret comparison, a replayable TOTP window, and admin enumeration via distinct login responses.

| | |
|---|---|
| **Severity** | LOW |
| **Confidence** | MEDIUM |
| **Area** | backend |
| **Remediation stage** | Stage 3 — Low priority (hygiene / defence-in-depth) |
| **Estimated complexity** | Low |

## Evidence

(1) `backend/app/api/v1/bot.py:68-75` uses `received != expected` instead of `hmac.compare_digest`. (2) `backend/app/auth/totp.py:23-44` accepts a code for the current step ±1 with no used-code tracking (enforced at `auth.py:239-249`) — replayable for ~90s. (3) `backend/app/api/v1/auth.py:151-165` (`_require_admin_candidate`) returns `403 not_an_admin` for non-admins but proceeds for admins, enabling admin-ID enumeration.

## Impact

Individually minor: a theoretical timing oracle on the webhook secret, a ~90s TOTP replay window, and admin-ID enumeration that aids targeted brute force.

## Suggested fix

(1) Use `hmac.compare_digest`. (2) Persist the last accepted TOTP timestep per super-admin and reject `<=` it. (3) Return a uniform generic response for admin and non-admin IDs on the login `request` endpoint.

## Acceptance criteria

- [ ] Webhook secret compared in constant time.
- [ ] A TOTP code cannot be reused within its window.
- [ ] The admin-login request response does not reveal admin status.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
