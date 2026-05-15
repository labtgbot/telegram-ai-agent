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

### POST /payment/create-invoice
```json
{ "package": "premium", "user_id": 12345 }
```
Response:
```json
{
  "invoice_id": "inv_123456",
  "stars_amount": 750,
  "tokens_amount": 2000,
  "telegram_invoice_link": "https://t.me/invoice/..."
}
```

### POST /payment/webhook
Telegram `successful_payment` payload.

### GET /payment/status/{invoice_id}
```json
{ "status": "completed", "tokens_credited": 2000, "transaction_id": "txn_789" }
```

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
