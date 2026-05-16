# PII minimization policy

GDPR (Art. 5(1)(c)) requires that personal data we process is *adequate,
relevant and limited to what is necessary*. This document describes how
the Telegram AI Agent stack enforces that principle in logs, traces and
internal tooling, plus the rules engineers must follow when adding new
log lines or telemetry.

## Pipeline

```
       ┌────────────────────┐
       │  application code  │  (structlog, FastAPI, workers)
       └─────────┬──────────┘
                 │
                 ▼
   ┌─────────────────────────────┐
   │  scrub_processor             │   ◀── app/core/log_scrubbing.py
   │  · redacts PII keys/values   │
   │  · runs before the renderer  │
   └─────────────┬───────────────┘
                 │
                 ▼
        JSON or console renderer
                 │
                 ▼
              stdout
```

The scrubber lives in
[`backend/app/core/log_scrubbing.py`](../../backend/app/core/log_scrubbing.py)
and is installed by `configure_logging()` so every structlog event goes
through it. Output ships to stdout where the platform log collector
forwards it; **no raw PII ever lands in the collector**.

## What gets redacted

* **By key name** — fields whose key matches one of:
  `password`, `secret`, `api_key`, `auth_token`, `init_data`,
  `email`, `phone`, `session_id`, `cookie`, `authorization`,
  `credit_card`, `cvv`. (Case-insensitive; common suffixes and
  prefixes are matched.)
* **By value pattern** — anywhere in the event:
  * RFC-5322 email addresses
  * JWTs (`eyJ…` three-part tokens)
  * Telegram bot tokens (`<bot-id>:<35+ chars>`)
  * 13–19 digit credit-card-shaped numbers

Redacted fields are replaced with the literal string `[REDACTED]`.

## What we keep on purpose

A small allow-list of *diagnostic identifiers* survives scrubbing because
we use them for correlation and debugging:

`event`, `level`, `logger`, `timestamp`, `request_id`, `trace_id`,
`span_id`, `user_id`, `telegram_id`, `chat_id`, `thread_id`, `job_id`,
`status`, `duration_ms`, `error`, `error_code`, `method`, `path`,
`route`, `endpoint`.

`user_id` and `telegram_id` are pseudo-identifiers — they're tied to
our subject-rights tooling (data export / deletion) but on their own
they don't reveal name, email, phone or location. We log them so
support can reproduce issues without requesting PII.

## Rules for engineers

1. **Never log a raw user message.** Log a hash, a length, or a
   classification label instead. If you absolutely must log content for a
   debug ticket, gate it behind a feature flag and remove the line before
   merging.
2. **Don't log Telegram `initData` payloads.** Log only the `auth_date`
   and the success/failure of the HMAC check.
3. **Don't log emails or phone numbers.** If a customer-support ticket
   needs them, write to the dedicated `support_audit_log` table — that
   path has its own retention and access controls.
4. **Pass identifiers, not bodies.** Prefer
   `logger.info("payment.completed", user_id=u.id, invoice_id=i.id)`
   over passing the whole order dict.
5. **New PII-shaped keys must be added to the scrubber.** When you
   introduce a new sensitive field, extend `_PII_KEY_PATTERNS` in
   `log_scrubbing.py` and add a test pinning the redaction.

## Audit checklist (per release)

* [ ] `rg "logger\.(info|warn|error)" backend/app` and skim new lines for
      raw PII.
* [ ] Run the `test_log_scrubbing.py` suite — it covers the published
      redaction rules.
* [ ] Verify any newly-added Sentry breadcrumbs are scrubbed too (Sentry
      runs an independent `before_send` hook — see
      `backend/app/core/observability.py`).
* [ ] Confirm log retention in the chosen platform is ≤ 90 days for
      application logs and ≤ 12 months for security events (per the
      Privacy Policy).

## Related documents

* [Privacy Policy](../legal/PRIVACY_POLICY.md) — declares what data we
  collect and our retention windows.
* [Security audit report](audit-report.md) — Phase-4 security baseline.
* [Threat model](threat-model.md) — STRIDE for the data plane.
