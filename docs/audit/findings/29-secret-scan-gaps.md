## Summary

The gitleaks config disables secret scanning across all Markdown and globally allowlists `change-me`/`CHANGEME`, and the npm-audit CI gate only fails on Critical, so HIGH JS advisories merge unblocked.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | devops |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`.gitleaks.toml:18-48` — `paths` includes `(^|/).+\.md$` (every `.md`) and globally allowlists `change-me`/`CHANGEME`. `.github/workflows/security.yml:99-108` runs `npm audit --omit=dev --audit-level=critical`.

## Impact

A real secret pasted into any `.md` (runbook, incident note) is invisible to the scanner, and new HIGH-severity dependency CVEs can land on `main` without blocking.

## Suggested fix

Narrow the gitleaks path allowlist to specific fixture dirs (e.g. `docs/**` only where needed) and scope the `change-me` allowlist to known placeholder lines; restore `--audit-level=high` with a short, time-boxed, individually-justified exceptions list.

## Acceptance criteria

- [ ] Secret scanning covers Markdown outside an explicit narrow allowlist.
- [ ] `npm audit` fails on new HIGH advisories.
- [ ] Existing placeholder lines are allowlisted narrowly, not globally.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
