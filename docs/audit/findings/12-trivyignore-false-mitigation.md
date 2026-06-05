## Summary

Fourteen HIGH/CRITICAL Next.js advisories are permanently suppressed in the CI security gate on the basis of an "ingress IP-allowlist + CSP nonces" compensating control that does not exist in the deployment.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | devops |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Medium |

## Evidence

`.trivyignore:15-31` (F-006) suppresses CVE-2026-44573 … GHSA-q4gf-8mx6-v5v3 citing the allowlist. The production ingress (`deploy/helm/telegram-ai-agent/values-production.yaml:133-153`) sets only body-size/timeouts/limit-rps; a repo-wide search for `whitelist-source-range` / allowlist annotations returns nothing. The admin host is served with no source-IP restriction.

## Impact

14 HIGH/CRITICAL Next.js advisories are waived from the CI gate behind a control that was never deployed, leaving the highest-value target (admin dashboard) exposed to those CVEs.

## Suggested fix

Either implement the claimed control (`nginx.ingress.kubernetes.io/whitelist-source-range` on the admin host) or remove the false justification and prioritise the Next.js upgrade. Do not suppress CVEs behind a non-existent mitigation.

## Acceptance criteria

- [ ] Either the IP-allowlist is actually configured on the admin ingress, or the Next.js CVEs are remediated and the `.trivyignore` entries removed.
- [ ] `.trivyignore` justifications reference only controls that are actually deployed.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
