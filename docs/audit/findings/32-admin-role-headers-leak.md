## Summary

The middleware sets `x-admin-role` and `x-admin-sub` on the response to the browser, leaking the admin's privilege level and id on every protected response for no functional benefit.

| | |
|---|---|
| **Severity** | LOW |
| **Confidence** | MEDIUM |
| **Area** | admin-dashboard |
| **Remediation stage** | Stage 3 — Low priority (hygiene / defence-in-depth) |
| **Estimated complexity** | Low |

## Evidence

`admin-dashboard/middleware.ts:63-66` — `response.headers.set("x-admin-role", payload.role)` and `set("x-admin-sub", payload.sub)`; no server code reads them.

## Impact

Minor information disclosure of the authenticated admin's id and privilege on every response, visible in dev tools / intermediaries.

## Suggested fix

Remove these `response.headers.set(...)` lines. If downstream identity propagation is needed, set them on the forwarded request headers and never trust inbound `x-admin-*`.

## Acceptance criteria

- [ ] Protected responses no longer carry `x-admin-role`/`x-admin-sub`.
- [ ] Identity propagation (if any) uses request headers only.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
