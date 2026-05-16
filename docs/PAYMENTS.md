# Payments (Telegram Stars)

Phase 2 introduces the paid token economy via the Telegram Stars currency
(`XTR`).  All payments flow through the Bot API — there is no third-party
processor; Telegram itself collects Stars and dispatches webhook updates
to the bot.

* Service: [`backend/app/services/payments.py`](../backend/app/services/payments.py)
* Catalog: [`backend/app/services/payment_packages.py`](../backend/app/services/payment_packages.py)
* REST routes: [`backend/app/api/v1/payment.py`](../backend/app/api/v1/payment.py)
* Bot handlers: [`backend/app/bot/handlers.py`](../backend/app/bot/handlers.py)
* Renewal worker: [`backend/app/workers/subscriptions.py`](../backend/app/workers/subscriptions.py)

## Catalog

| Code         | Title       | Tokens | Stars | Type         |
|--------------|-------------|--------|-------|--------------|
| `starter`    | Starter     | 500    | 250 ⭐ | one-time     |
| `basic`      | Basic       | 1,200  | 500 ⭐ | one-time     |
| `premium`    | Premium     | 2,000  | 750 ⭐ | one-time     |
| `pro_monthly`| Pro Monthly | 2,000  | 500 ⭐ | subscription (30d) |

Catalog is static for Phase 2.  Admin-overridable pricing lands in
Phase 3 (see `docs/PRICING_STRATEGY.md`).

## End-to-end flow

```
Mini App ──POST /payment/create-invoice──▶ FastAPI
                                              │
                                              ├─ persist Transaction(status=pending,
                                              │                       payment_id="invoice:<payload>")
                                              ├─ call Bot.createInvoiceLink
                                              └─ return telegram_invoice_link
            ◀───── invoice_link ─────────────┘

Telegram.WebApp.openInvoice(link)
       │
       ▼ user pays Stars
       │
Telegram ──webhook pre_checkout_query──▶ FastAPI dispatcher ──▶ handle_pre_checkout_query
                                              │
                                              └─ answerPreCheckoutQuery(ok=True)

Telegram ──webhook successful_payment──▶ FastAPI dispatcher ──▶ handle_successful_payment
                                              │
                                              ├─ idempotency check on telegram_payment_charge_id
                                              ├─ TokenService.add(...)
                                              ├─ Transaction → status=completed,
                                              │                payment_id="tg:<charge_id>"
                                              └─ (Pro) extend Subscription.expires_at + 30d
```

## Idempotency

The acceptance criterion is that a duplicate `successful_payment` webhook
must never double-credit the user.  We rely on two layers:

1. **Application layer.** `PaymentService.finalize_successful_payment`
   first looks up a `Transaction` keyed by `payment_id="tg:<charge_id>"`.
   If one exists, the call short-circuits and returns the original
   `PaymentResult` with `already_processed=True` — no balance change, no
   second audit row.
2. **Database layer.** Migration `0003_payment_idempotency` adds a partial
   unique index on `transactions.payment_id` so that two concurrent
   webhook deliveries cannot both insert.  The losing transaction sees
   `IntegrityError` and is converted to the same idempotent result.

The same mechanism handles other replay sources:

| Marker prefix         | Source                                       |
|-----------------------|----------------------------------------------|
| `invoice:<payload>`   | Pending row written when invoice is created  |
| `tg:<charge_id>`      | Stable Telegram-issued charge id (winner)    |
| `renewal:<sub>:<idx>` | Periodic credit from the renewal worker      |

## Subscriptions

Pro is a recurring monthly bundle (currently `pro_monthly`).  The first
successful payment creates (or extends) a row in `subscriptions`:

* `plan_code = "pro"`
* `status = "active"`
* `auto_renew = True`
* `expires_at = max(existing, now) + 30 days`

Telegram Stars subscriptions emit their own `successful_payment` updates
on renewal — those flow through the standard finaliser because each
renewal has a fresh `telegram_payment_charge_id`.

For environments without Stars-native subscriptions (or while polling
catches up), the **renewal worker** keeps things consistent:

```bash
python -m app.workers.subscriptions
```

Schedule it daily (cron / k8s CronJob / Celery beat in Phase 3).  The
worker:

1. Selects active auto-renew subscriptions where `expires_at <= now()`.
2. Credits the package's tokens through `TokenService.add` with a
   `purchase` transaction marked `payment_id="renewal:<sub_id>:<index>"`
   (the index increments per period, giving each renewal a unique key).
3. Extends `expires_at` by `subscription_days`.
4. Refreshes `users.premium_expires_at`.

Reruns are safe — the unique `payment_id` blocks duplicate credits.
Cancelled subscriptions (`status != "active"` or `auto_renew=False`) are
skipped.

## Errors

`PaymentService` raises typed exceptions; the REST layer maps them to
HTTP responses (see `docs/API_REFERENCE.md > Payment Endpoints`):

| Exception                       | Meaning                                           |
|---------------------------------|---------------------------------------------------|
| `PackageNotFoundError`          | Unknown `package` code                            |
| `InvoiceNotFoundError`          | `status` lookup or pre-checkout for unknown id    |
| `InvoicePayloadInvalidError`    | Payload format malformed                          |
| `InvoiceCurrencyMismatchError`  | Currency in webhook ≠ `XTR`                       |
| `InvoiceAmountMismatchError`    | Stars total in webhook ≠ catalog price            |
| `TelegramApiError`              | Upstream Bot API failure (mapped to 502)          |

## Tests

Two suites cover this surface end-to-end:

* `backend/tests/test_payments_service.py` — DB-backed service tests
  (skip cleanly when `DATABASE_URL` is unset).  Covers happy-path
  invoice creation, pre-checkout validation, successful finalisation,
  duplicate-webhook idempotency, currency/amount mismatch, subscription
  creation + extension, and the renewal worker (idempotent across reruns,
  ignores cancelled subscriptions).
* `backend/tests/test_payment_endpoints.py` — endpoint tests with a
  stubbed `PaymentService`.  Covers init-data auth (401 on
  missing/tampered), 404 on unknown package, 502 on Telegram failure,
  422 on blank package, and the full status lookup lifecycle.
