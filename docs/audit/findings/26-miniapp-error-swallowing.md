## Summary

Profile/settings flows catch every error and show a generic string (or nothing), discarding status and message and never reporting to Sentry, so real auth failures look like empty data.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | mini-app |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`mini-app/src/pages/ProfilePage.tsx:41-49` sets `error = null` on 404; `mini-app/src/pages/SettingsPage.tsx:72-73,87-88` use bare `catch {}` with a generic message.

## Impact

Combined with the broken-routes finding, a permanently-404ing endpoint gives zero feedback and zero diagnostics; 401/403 auth failures are indistinguishable from "no data".

## Suggested fix

Distinguish 401/403 from 404/5xx, surface a real message, and `Sentry.captureException` unexpected errors.

## Acceptance criteria

- [ ] Auth errors are shown distinctly from missing data.
- [ ] Unexpected errors are reported to Sentry.
- [ ] Tests cover the 401/403 vs 404 branches.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
