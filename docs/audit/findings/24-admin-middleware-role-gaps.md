## Summary

The most privileged admin pages (`/system`, `/content`) are missing from the middleware role map and therefore only require `analyst`, inconsistent with the `super_admin` gate on `/pricing` and `/settings`.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | MEDIUM |
| **Area** | admin-dashboard |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`admin-dashboard/middleware.ts:13-32` — `ROUTE_ROLES` lists `/pricing`, `/settings` (super_admin), `/broadcast`, `/users`, `/transactions` (support_admin) and defaults everything else to `analyst`. `/system` (manages admin users/roles, rate limits, maintenance, Composio) is not listed.

## Impact

A low-privilege analyst can load `/system` and trigger server-side reads of admin/role/rate-limit/Composio config; the front-end route-protection model is inconsistent and gives a false sense of gating.

## Suggested fix

Add `{ prefix: "/system", required: "super_admin" }` and an appropriate entry for `/content`; keep the backend as the authoritative check.

## Acceptance criteria

- [ ] `/system` requires super_admin and `/content` an appropriate role at the middleware layer.
- [ ] Tests assert an analyst is redirected away from `/system`.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
