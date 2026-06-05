## Summary

The global query client retries all failures once (including auth/4xx), and the production build emits public source maps.

| | |
|---|---|
| **Severity** | LOW |
| **Confidence** | MEDIUM |
| **Area** | mini-app |
| **Remediation stage** | Stage 3 — Low priority (hygiene / defence-in-depth) |
| **Estimated complexity** | Low |

## Evidence

`mini-app/src/services/queryClient.ts:18` sets `retry: 1` with no predicate (balance, packages, transactions, referral all use it). `mini-app/vite.config.ts` sets `build.sourcemap: true`.

## Impact

Pointless retries double latency/load on auth-rejecting endpoints; full original TypeScript is published alongside the bundle (no secrets are exposed, so impact is source disclosure).

## Suggested fix

Use a `retry` predicate that returns `false` for 4xx and retries only network/5xx; set `sourcemap: false` (or `"hidden"` + upload to Sentry only) for production builds.

## Acceptance criteria

- [ ] 4xx responses are not retried.
- [ ] Production builds do not publish public source maps.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
