## Summary

The Next.js admin dashboard falls back to a publicly-known signing secret when `ADMIN_JWT_SECRET` is unset, and — unlike the Python backend — has no production guard that refuses to start with the placeholder.

| | |
|---|---|
| **Severity** | CRITICAL |
| **Confidence** | HIGH |
| **Area** | admin-dashboard |
| **Remediation stage** | Stage 0 — Blocker (fix before any production deploy) |
| **Estimated complexity** | Low |

## Evidence

`admin-dashboard/lib/env.ts:15`
```ts
jwtSecret: process.env.ADMIN_JWT_SECRET ?? "change-me",
```
`lib/auth/tokens.ts` verifies admin access tokens with `serverEnv().jwtSecret`. The repo even ships `admin-dashboard/scripts/dev-token.mjs` which mints a valid `super_admin` token using the same default. The Python backend protects against this via `assert_production_safe` (`backend/app/core/config.py:333-353`) but the Node side has no equivalent.

## Impact

Anyone who knows the committed default secret can forge a `super_admin` access token, set the `admin_access_token` cookie, pass middleware verification and gain full admin-UI access (user bans, token grants, pricing, broadcasts, admin-role management). If the backend shares the same fallback secret, this is a complete authentication bypass of the admin surface.

## Suggested fix

Remove the `?? "change-me"` fallback. Throw at module load / server start when `ADMIN_JWT_SECRET` is unset or equals `change-me` while `NODE_ENV === "production"`, mirroring the backend's fail-closed behaviour. Require a high-entropy secret.

## Acceptance criteria

- [ ] `serverEnv()` throws in production when `ADMIN_JWT_SECRET` is missing or equals the placeholder.
- [ ] A forged token signed with `change-me` is rejected by middleware in a production build.
- [ ] `dev-token.mjs` only works against a dev environment / explicit dev secret.
- [ ] Regression test covers the production-guard path.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
