# API Reference (Draft)

Base URL: `/api/v1`.

## Authentication

- User endpoints: `X-Telegram-Init-Data` header (signed by Telegram WebApp).
- Admin endpoints: `Authorization: Bearer <admin_jwt>` + `X-Admin-ID`.

## User Endpoints

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
| 401  | `invalid_init_data` | Missing/forged init-data header |
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

> Полная OpenAPI-спецификация будет автогенерироваться FastAPI (`/docs`).
