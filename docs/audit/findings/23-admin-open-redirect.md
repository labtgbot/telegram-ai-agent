## Summary

The post-login redirect only checks `from.startsWith("/")`, which accepts protocol-relative URLs like `//evil.com`, redirecting an authenticated admin off-site.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | admin-dashboard |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`admin-dashboard/components/auth/login-form.tsx:86-88`
```ts
const target = from && from.startsWith("/") ? from : "/dashboard";
router.replace(target);
```
`from` originates from `middleware.ts:37`.

## Impact

Phishing — after login the admin is silently sent to an attacker domain for credential/session harvesting on a lookalike page.

## Suggested fix

Reject values starting with `//` (and backslash variants); accept only `/^\/(?!\/)/`, or parse with `new URL(from, origin)` and confirm same-origin.

## Acceptance criteria

- [ ] `//evil.com` and `/\evil.com` are rejected and fall back to `/dashboard`.
- [ ] Only same-origin relative paths are honoured (test).

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
