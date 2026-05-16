# Alternative Payment Rails — TON & Stripe

Telegram Stars (`XTR`) is the canonical rail for v1.0.0
([`docs/PAYMENTS.md`](PAYMENTS.md)). This document describes the
**optional** alternative rails that ship behind feature flags so the
production launch can proceed with Stars only and enable them later
without redeploying the schema.

> Status (v1.0.0): both rails are disabled by default. See the
> [`docs/LAUNCH_CHECKLIST.md`](LAUNCH_CHECKLIST.md) §3 for the launch
> defaults.

## Why Stars is enough at launch

* Stars settles inside Telegram — no third-party PCI / KYC surface.
* The catalog (`backend/app/services/payment_packages.py`) already
  prices every package in Stars; introducing a new currency requires a
  conversion table and is a pricing decision, not a launch blocker.
* `Transaction.payment_id` is provider-agnostic. The `tg:<charge_id>`
  prefix used today is one of several documented in
  [`docs/PAYMENTS.md`](PAYMENTS.md); adding `ton:<txhash>` or
  `stripe:<pi_…>` re-uses the same idempotency mechanism.

## Feature flags

Production Helm values default both to `false`:

```yaml
backend:
  env:
    PAYMENTS_TON_ENABLED: "false"
    PAYMENTS_STRIPE_ENABLED: "false"
```

When a flag is `false`:

* the Mini App hides the corresponding "Pay with …" button;
* the REST endpoint returns `404 not_found` for that provider so
  no rogue webhook can credit tokens.

## TON

The Open Network rail is attractive for high-value purchases (1 TON
≈ 4–5 USD, with no Stars conversion fee) and for users who already
hold TON in `@wallet`. Integration sketch:

1. **Address provisioning.** Generate a per-invoice deposit address via
   `tonweb` / `ton-core` and persist the `address` + expected
   `amount_nano` next to the existing `transactions` row. Stamp
   `payment_id="ton:<invoice_uuid>"` as the pending marker.
2. **Tracking.** A worker polls a public TON HTTP API (Toncenter,
   GetBlock) for incoming transfers to each address. Match by
   `(address, amount_nano)` and capture the on-chain `tx_hash`.
3. **Finalisation.** Call `PaymentService.finalize_successful_payment`
   with `telegram_payment_charge_id=f"ton:{tx_hash}"`. The existing
   idempotency layer (Migration `0003_payment_idempotency`) deduplicates
   re-orgs and worker restarts.
4. **Subscriptions.** TON does not have native subscriptions; the
   renewal worker (`backend/app/workers/subscriptions.py`) can extend
   `Subscription.expires_at` on each manual top-up, mirroring the Stars
   `pro_monthly` flow.

Operational notes:

* Hold the master mnemonic in **the same** secret store as the bot
  token; rotate quarterly.
* Reconciliation: a daily report under `deploy/monitoring/` should
  compare `transactions WHERE payment_id LIKE 'ton:%'` against the
  wallet's on-chain history.
* Refunds require a manual outbound transfer + an admin-issued
  `refund` row — there is no programmatic refund.

## Stripe

Stripe gives us credit-card support for users outside Telegram (and
for B2B sales of large token bundles). Integration sketch:

1. **Provisioning.** Create a Stripe `PaymentIntent` per invoice with
   `metadata={"transaction_id": …, "package": …}` and store the
   `payment_intent.id` against the pending row
   (`payment_id="stripe:pi_…"`).
2. **Client.** The mini-app renders Stripe Elements over the existing
   `/payment/create-invoice` response when `provider="stripe"` is
   requested.
3. **Webhook.** A new endpoint `POST /payment/webhook/stripe` verifies
   the `Stripe-Signature` header against `STRIPE_WEBHOOK_SECRET`,
   handles `payment_intent.succeeded`, and dispatches into
   `PaymentService.finalize_successful_payment` with
   `telegram_payment_charge_id=f"stripe:{payment_intent.id}"`.
4. **Refunds.** Surface a refund button in the admin CRM that calls
   `stripe.Refund.create` and writes a `refund:<refund_id>` audit row.

Operational notes:

* Use Stripe **Restricted Keys** scoped to the events above and a
  **separate** key per environment.
* Stripe enforces PCI SAQ-A when using Elements with hosted fields —
  no card data ever hits our backend, but the privacy notice
  (`docs/legal/PRIVACY_POLICY.md`) must list Stripe as a subprocessor
  before launch ([`docs/legal/SUBPROCESSORS.md`](legal/SUBPROCESSORS.md)).
* Currency: invoices are priced in USD; the `pricing` service multiplies
  the Stars amount by the configured `STRIPE_STARS_USD_RATE`
  (recommended default: 1 ⭐ ≈ 0.015 USD, the public Telegram exchange
  rate). Admins can override the rate from the CRM without a redeploy.

## Audit trail

Whatever the rail, the audit story is the same:

| Table | Column | What it stores |
| --- | --- | --- |
| `transactions` | `payment_id` | `tg:<charge>` / `ton:<txhash>` / `stripe:<pi>` |
| `transactions` | `provider` *(new)* | `stars` \| `ton` \| `stripe` |
| `token_usage_logs` | `payment_ref` | FK back to `transactions.id` |
| `admin_audit_logs` | `event` | `refund.created`, `payment.manual_credit` |

The `provider` column is a **future** schema change, not a v1.0.0
deliverable. Until it lands, the `payment_id` prefix is the source of
truth and the read-side analytics use a `CASE` on the prefix.

## Roll-out plan

1. Ship v1.0.0 with Stars only (current state).
2. After two weeks of stable Stars revenue, flip
   `PAYMENTS_TON_ENABLED=true` on **staging** and run a Toncenter
   testnet end-to-end purchase.
3. Schedule a maintenance window, apply the `transactions.provider`
   migration, and enable TON in production.
4. Repeat for Stripe once the legal subprocessor list is updated.

Linked work: the schema migration, worker and CRM affordances are
tracked under separate issues; this document is the design reference.
