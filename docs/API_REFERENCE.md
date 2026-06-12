# API Reference

Base URL: `/api/v1` (configurable via `API_V1_PREFIX`).

This document is curated alongside the **machine-readable OpenAPI spec**
that FastAPI auto-generates from the codebase:

| Form         | Where                                                              |
|--------------|--------------------------------------------------------------------|
| Swagger UI   | `https://bot.example.com/docs` (production), `http://localhost:8000/docs` |
| Redoc        | `https://bot.example.com/redoc`                                    |
| Raw JSON     | `https://bot.example.com/openapi.json`                             |
| CI artifact  | `openapi.json` produced by `.github/workflows/openapi.yml` on every push, attached to release tags |

To re-generate the spec offline:

```bash
cd backend
python -c "import json; from app.main import create_app; \
  print(json.dumps(create_app().openapi(), indent=2))" > openapi.json
```

If endpoint behaviour ever drifts from this Markdown, **the FastAPI
spec is the source of truth** — open an issue or PR to bring this file
back in sync.

## Authentication

- User endpoints: `X-Telegram-Init-Data` header (signed by Telegram WebApp).
- Admin API endpoints: `Authorization: Bearer <admin_access_jwt>`.
  Access tokens are short-lived; refresh tokens are server-side sessions and
  must be rotated through `/auth/admin/refresh`.
- Bot webhook: `POST /api/v1/bot/webhook/{secret}` — secret rotated via
  `TELEGRAM_WEBHOOK_SECRET`; processed Telegram `update_id` values are
  remembered in Redis to short-circuit redeliveries.
- Health probes (`/health`, `/health/live`, `/health/ready`) are public.

### Admin Auth

`POST /auth/admin/login/request` issues a one-time code for an admin
Telegram ID. In development it returns the code in the response; in production
delivery is via the bot.

`POST /auth/admin/login/verify` exchanges the one-time code (and TOTP for
super-admins with TOTP enabled) for:

```json
{
  "access_token": "eyJ...",
  "refresh_token": "eyJ...",
  "token_type": "Bearer",
  "expires_in": 900
}
```

`POST /auth/admin/refresh` rotates the refresh token. The old refresh token is
marked used/revoked server-side, and replaying it returns `401
refresh_token_reused`. A revoked logout token returns `401
refresh_token_revoked`; expired or malformed tokens return `401`.

`POST /auth/admin/logout` revokes the active refresh session:

```json
{ "refresh_token": "eyJ..." }
```

Response (`200`):

```json
{ "status": "ok" }
```

## User Endpoints

### GET /user/me

Returns the current Mini App profile for the authenticated Telegram user.

```json
{
  "id": 42,
  "telegram_id": 100200,
  "username": "alice",
  "first_name": "Alice",
  "last_name": null,
  "language_code": "en",
  "role": "user",
  "referral_code": "ABC123",
  "is_premium": false,
  "is_banned": false,
  "premium_expires_at": null,
  "created_at": "2024-03-04T00:00:00+00:00",
  "totp_enabled": false
}
```

### GET /user/balance
```json
{
  "token_balance": 450,
  "is_premium": false,
  "premium_expires_at": null,
  "daily_bonus_available": true
}
```

### GET /user/usage-history
Параметры: `page`, `limit`.

### GET /user/referral
```json
{
  "referral_code": "ABC123",
  "referrals_count": 5,
  "bonus_tokens_earned": 500,
  "referral_link": "https://t.me/YourBot?start=ABC123"
}
```

### GET /user/daily-bonus

Snapshot for the Mini App's claim card. Read-only; safe to call on every
home-page render.

```json
{
  "available": true,
  "enabled": true,
  "streak_day": 2,
  "next_amount": 15,
  "last_claim_date": "2026-05-15",
  "next_available_at": "2026-05-17T00:00:00+00:00",
  "amounts": [10, 12, 15, 20]
}
```

- `available` — `true` if the user can claim **right now** (UTC day).
- `streak_day` — current persisted streak (0 for a brand-new user, ≥1 after
  at least one claim).
- `next_amount` — what the *next* successful claim will credit.
- `next_available_at` — the next UTC midnight at which the cooldown lifts.
- `amounts` — the active ladder (admin override or env default).

### POST /user/daily-bonus

Credits today's bonus (idempotent per UTC day). Streak grows when the previous
claim was *yesterday*; otherwise it resets to day 1. The ladder defaults to
`10 → 12 → 15 → 20` (capped at the last value).

Response (`200`):
```json
{
  "amount": 15,
  "streak_day": 3,
  "new_balance": 615,
  "transaction_id": 9123,
  "claim_date": "2026-05-16",
  "next_available_at": "2026-05-17T00:00:00+00:00"
}
```

| HTTP | `detail` | Trigger |
|------|----------|---------|
| 401  | `invalid_init_data` / `missing_init_data` / `init_data_query_unsupported` | Missing/forged init-data header, or `initData` sent in the URL query |
| 403  | `daily_bonus_disabled` | Master switch is off (env or `admin_settings.daily_bonus.enabled = false`) |
| 404  | `user_not_found` | Authenticated user vanished mid-request |
| 409  | `{"code": "daily_bonus_already_claimed", "next_available_at": "…"}` | Already claimed today |

Idempotency: even with two parallel requests, exactly one credit is recorded
(`transactions.payment_id = "daily_bonus:user:<id>:date:<YYYY-MM-DD>"`) and
the duplicate insert into `daily_bonus_claims` is rejected by the
`(user_id, claim_date)` UNIQUE constraint.

### GET /user/me/export

Returns a JSON export of the authenticated user's account data.

### DELETE /user/me

Schedules account anonymisation with a 30-day grace period.

Response (`202`):

```json
{
  "request_id": 99,
  "status": "pending",
  "requested_at": "2026-06-07T00:00:00+00:00",
  "scheduled_for": "2026-07-07T00:00:00+00:00",
  "detail": "deletion_scheduled"
}
```

## Payment Endpoints

Implemented in Phase 2 (`backend/app/api/v1/payment.py`). Both endpoints require `X-Telegram-Init-Data`; the caller is identified by the signed payload, so no `user_id` is taken from the request body.

### POST /payment/create-invoice

Request:
```json
{ "package": "premium" }
```

Response (`200`):
```json
{
  "invoice_id": "9f3c…b1",
  "stars_amount": 750,
  "tokens_amount": 2000,
  "telegram_invoice_link": "https://t.me/$XXXX",
  "transaction_id": 4711,
  "is_subscription": false
}
```

| HTTP | `detail` | Trigger |
|------|----------|---------|
| 401  | `invalid_init_data` / `missing_init_data` / `init_data_query_unsupported` | Missing/forged init-data header, or `initData` sent in the URL query |
| 404  | `package_not_found` | Unknown package code |
| 422  | Pydantic validation | Blank/oversized `package` |
| 502  | `telegram_api_error` | `createInvoiceLink` upstream failure |

The created `transactions` row starts at `status="pending"` with `payment_id="invoice:<invoice_id>"`; it is flipped to `completed` only after the `successful_payment` webhook lands.

### Telegram Bot webhook — `pre_checkout_query` / `successful_payment`

Posted to the existing `POST /bot/webhook/{secret}` endpoint by Telegram. The dispatcher (`backend/app/bot/dispatcher.py`) routes them to:

* `handle_pre_checkout_query` — validates payload + replies via `answerPreCheckoutQuery` (ok=True/False).
* `handle_successful_payment` — credits tokens via `PaymentService.finalize_successful_payment`, upgrades the pending transaction to `completed`, and (for Pro) extends `subscriptions.expires_at`. Duplicate webhooks with the same `telegram_payment_charge_id` are silently ignored.

### GET /payment/status/{invoice_id}

Response (`200`):
```json
{
  "invoice_id": "9f3c…b1",
  "status": "completed",
  "package": "premium",
  "tokens_credited": 2000,
  "stars_amount": 750,
  "transaction_id": 4711,
  "created_at": "2026-05-16T09:14:32Z",
  "completed_at": "2026-05-16T09:14:55Z",
  "telegram_payment_charge_id": "abcd…"
}
```

`status ∈ {pending, completed, failed}`. `tokens_credited` is `0` while the invoice is still pending. Returns `404 invoice_not_found` if the invoice is unknown or belongs to a different user.

## AI Generation Endpoints

- `POST /generate/image` — токены: 30/50/100
- `POST /generate/video` — токены: 100/250/800
- `POST /generate/text`  — токены: 1/5/10
- `POST /generate/voice` — токены: 5
- `POST /generate/document` — токены: 20
- `POST /generate/search` — токены: 3

Все возвращают `{ "result": ..., "tokens_spent": N, "remaining_balance": M }`.

## Admin Endpoints

### GET /admin/dashboard?period=7d
KPI: users, revenue, tokens, usage.

### GET /admin/users
Параметры: `page`, `limit`, `search`, `filter_premium`, `sort_by`, `sort_order`.

### POST /admin/users/{user_id}/add-tokens
```json
{ "tokens": 100, "reason": "Support compensation" }
```

### POST /admin/users/{user_id}/ban
```json
{ "reason": "Spam", "duration_days": 7 }
```

### GET /admin/pricing
### POST /admin/pricing/update
### GET /admin/analytics/revenue
### GET /admin/analytics/user-behavior
### POST /admin/broadcast

### GET /admin/transactions
Filterable ledger; `?status`, `?type`, `?date_from`, `?date_to`, `?package`.

### POST /admin/transactions/{id}/retry-webhook
Idempotently re-finalises a `pending` Stars payment by replaying the
existing webhook dispatcher.

### POST /admin/transactions/{id}/refund
Issues `refundStarPayment` upstream + inserts a compensating row in
`transactions`. Both actions land in `admin_audit_logs`.

### GET /admin/analytics/funnel
### GET /admin/analytics/retention?day=1|7|30
### GET /admin/analytics/ltv
### GET /admin/segments
### POST /admin/segments
### GET /admin/content/{kind}
### PUT /admin/content/{kind}/{id}
### GET /admin/settings
### PUT /admin/settings/{key}
### GET /admin/system/audit-log

## Compliance & legal

| Method | Path                          | Purpose                                                 |
|--------|-------------------------------|---------------------------------------------------------|
| `POST` | `/compliance/age-verify`      | One-shot age confirmation; sets `users.age_verified`.   |
| `GET` | `/user/me/export`             | JSON export of the caller's account data.               |
| `DELETE` | `/user/me`                  | Schedules account deletion with a 30-day grace period.  |
| `POST` | `/user/me/cancel-deletion`   | Cancels a pending deletion within the grace window.     |

Public legal text is served as Markdown by the app shell:
`GET /privacy`, `GET /terms` (not under `/api/v1`).

## Webhooks & health

| Method | Path                              | Purpose                              |
|--------|-----------------------------------|--------------------------------------|
| `POST` | `/bot/webhook/{secret}`           | Telegram Bot API webhook entry-point |
| `GET`  | `/health`                         | Full readiness (DB + Redis)          |
| `GET`  | `/health/live`                    | Liveness probe                       |
| `GET`  | `/health/ready`                   | Readiness probe                      |
| `GET`  | `/metrics` *(when enabled)*       | Prometheus scrape target             |

## Conventions

- All requests/responses use `application/json` with UTF-8 unless
  explicitly noted (Markdown for `/privacy` and `/terms`).
- Timestamps are RFC 3339 in UTC (`2026-05-16T09:14:32Z`).
- Error envelope: HTTP status + `{ "detail": "<code-or-message>" }`
  (see per-endpoint tables for the registered `detail` codes).
- Idempotency: `payment_id` and `transactions.payment_id` carry the
  natural key for de-duplication (`invoice:<id>`, `daily_bonus:user:
  <uid>:date:<YYYY-MM-DD>`, etc.).
- Pagination: cursorless `?page=N&limit=M`, where `1 ≤ limit ≤ 100`.

> For the complete, always-current schema (request models, response
> models, validation errors), use the **OpenAPI spec** linked at the
> top of this document.
