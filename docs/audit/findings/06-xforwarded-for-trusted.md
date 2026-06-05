## Summary

The client-IP helper takes the first `X-Forwarded-For` hop verbatim with no trusted-proxy allowlist; the value is used both as the anonymous rate-limit bucket key and as the source IP recorded in admin audit logs.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Medium |

## Evidence

`backend/app/api/rate_limit.py:70-85` returns `fwd.split(",",1)[0].strip()` with no validation. `main.py` configures no `ProxyHeadersMiddleware`/trusted-host. The same `x-forwarded-for.split(",")[0]` pattern records audit IPs in `admin_users.py:242`, `admin_analytics.py:61`, `admin_pricing.py:185`, `admin_content.py:84`, `admin_system.py:65`, `admin_broadcasts.py:179`.

## Impact

Combined with the `request.state.user` bug, the only enforced limit (anonymous per-IP) is trivially defeated by sending a random `X-Forwarded-For` per request. Audit-log IP fields can be forged, undermining forensic value.

## Suggested fix

Resolve the client IP from the right-most untrusted hop using a configured trusted-proxy count (or `uvicorn --forwarded-allow-ips` / Starlette `ProxyHeadersMiddleware`). Never trust the left-most XFF entry directly. Reuse the corrected helper for audit IP capture.

## Acceptance criteria

- [ ] Client IP is derived only from trusted proxies (configurable).
- [ ] Spoofing `X-Forwarded-For` no longer yields a fresh rate-limit bucket (test).
- [ ] Audit logs record the real peer IP.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
