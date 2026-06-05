## Summary

Attacker-controlled Telegram profile fields are written into the admin CSV export without neutralising leading formula characters.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`backend/app/services/admin_users.py:518-528` (`_csv_row`/`_fmt`) writes `username`, `first_name`, `last_name` via `csv.writer` with no neutralisation of leading `=`, `+`, `-`, `@`. These values are user-set via the Telegram profile and enter the DB via `upsert_telegram_user`.

## Impact

A user setting their name to e.g. `=HYPERLINK(...)` or `=cmd|'/c calc'!A1` causes formula execution when an admin opens the export in Excel/LibreOffice/Sheets — data exfiltration or command execution on the admin's machine.

## Suggested fix

Sanitise cells beginning with `= + - @` (and control chars) by prefixing a single quote (or wrapping/escaping), centralised in `_fmt`.

## Acceptance criteria

- [ ] Exported cells beginning with a formula character are neutralised.
- [ ] A test exports a user named `=1+1` and asserts the cell is escaped.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
