## Summary

Several uniqueness/index objects exist only in migrations and not in the SQLAlchemy models, so any schema built from `Base.metadata` (tests, `create_all`) silently lacks the guards, and `alembic --autogenerate` would propose dropping them.

| | |
|---|---|
| **Severity** | HIGH |
| **Confidence** | HIGH |
| **Area** | backend |
| **Remediation stage** | Stage 1 — High priority (security / data-integrity) |
| **Estimated complexity** | Medium |

## Evidence

`uq_welcome_messages_active_per_locale` (partial unique) is created in `20260516_0009_admin_content.py:168-174` but absent from `app/models/welcome_message.py:57-60`. `uq_transactions_payment_id` (partial unique, payment idempotency) and `ix_transactions_payment_status` are created in `20260516_0003_payment_idempotency.py:37-49` but absent from `app/models/transaction.py:58-66`. `ix_transactions_created` differs: model declares plain ascending (`transaction.py:65`) while migration created it on `created_at DESC` (`20260515_0001:132-137`).

## Impact

Schemas built from models (tests, any `create_all` path) lack the welcome-message and payment-idempotency uniqueness guards, allowing duplicate active welcomes / double-credited payments in those environments; and `--autogenerate` output is unreliable.

## Suggested fix

Add the missing `Index(..., unique=True, postgresql_where=...)` declarations to the `WelcomeMessage` and `Transaction` models so models match migrations, and align the `ix_transactions_created` definition.

## Acceptance criteria

- [ ] Models and migrations agree (a fresh `--autogenerate` is empty/no-op).
- [ ] `create_all`-built schemas include the payment-idempotency and welcome-uniqueness indexes.
- [ ] A test builds the schema from models and asserts the unique indexes exist.

---
_Filed as part of the full-logic audit requested in #136. See `docs/audit/README.md` for the complete report._
