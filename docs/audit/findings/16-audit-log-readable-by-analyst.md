## Summary

The audit-log read endpoint is gated only by `get_current_admin` (ANALYST+), exposing every admin's source IP and user-agent to the lowest-privileged role while mutations require support_admin+.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | MEDIUM |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`backend/app/api/v1/admin_users.py` — `list_audit_log_endpoint` depends on `get_current_admin` (ANALYST floor) whereas write endpoints use `require_role(SUPPORT_ADMIN)`.

## Impact

An analyst (intended least-privilege) can enumerate the activity, IPs and UAs of super_admin/support_admin accounts — reconnaissance for targeting higher-privileged admins.

## Suggested fix

Gate audit-log reads behind `require_role("support_admin")` (or higher) unless analyst access is an explicit product requirement.

## Acceptance criteria

- [ ] Audit-log reads require support_admin or higher.
- [ ] Tests assert an analyst is denied audit-log reads.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
