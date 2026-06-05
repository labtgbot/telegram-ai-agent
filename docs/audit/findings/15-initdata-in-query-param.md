## Summary

The init-data auth dependency accepts the credential from the URL query string, so it leaks into access logs, proxy logs, browser history and `Referer` headers.

| | |
|---|---|
| **Severity** | MEDIUM |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 2 — Medium priority (correctness / hardening) |
| **Estimated complexity** | Low |

## Evidence

`backend/app/auth/dependencies.py:116-119`
```python
raw = x_telegram_init_data or request.query_params.get("initData")
```
Used by `generate.py`, `user.py`, `payment.py`. initData is a bearer-style credential valid until `telegram_init_data_max_age`.

## Impact

Leaked initData can be replayed within its validity window. Sensitive-credential-in-URL is an OWASP-flagged weakness.

## Suggested fix

Accept initData only from the `X-Telegram-Init-Data` header (and/or POST body). If a query-param fallback must remain, scope it narrowly and ensure logging redacts `initData`.

## Acceptance criteria

- [ ] initData is read from the header (and/or body), not the query string.
- [ ] If a legacy fallback remains, `initData` is redacted from logs.
- [ ] Tests confirm header-based auth works and query-param is removed/deprecated.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
