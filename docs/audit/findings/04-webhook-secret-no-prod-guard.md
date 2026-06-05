## Summary

`telegram_webhook_secret` defaults to empty (verification disabled) and the production safety check does not require it, so a misconfigured deploy accepts forged Telegram updates from anyone.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Low |

## Evidence

`backend/app/api/v1/bot.py:68-75`
```python
def _check_secret(expected, received):
    if not expected:
        return  # secret disabled in this environment
    if not received or received != expected:
        raise HTTPException(401, "invalid_webhook_secret")
```
`backend/app/core/config.py:120` sets `telegram_webhook_secret` default `""`, and `assert_production_safe` (`config.py:333-353`) only validates `admin_jwt_secret` — it does not require the webhook secret. The comparison also uses `!=` rather than `hmac.compare_digest`.

## Impact

With the default config anyone who knows the webhook URL can POST forged updates: impersonate arbitrary `from.id`/`chat.id`, trigger `/start` with attacker-chosen referral payloads, claim daily bonuses, and drive paid AI generation. (`successful_payment` is separately validated, but the registration/bonus/generation surface is fully spoofable.)

## Suggested fix

Require a non-empty `telegram_webhook_secret` in production by extending `assert_production_safe`, fail closed when missing, and replace `!=` with `hmac.compare_digest`.

## Acceptance criteria

- [ ] `assert_production_safe` fails when the webhook secret is empty outside dev/test.
- [ ] Webhook secret comparison uses `hmac.compare_digest`.
- [ ] A request with a missing/incorrect secret is rejected in a production config (test).

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
