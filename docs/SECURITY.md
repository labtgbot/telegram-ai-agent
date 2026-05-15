# Security Best Practices

## Authentication

- **User**: Telegram WebApp `initData` подписывается ботом, верификация HMAC по `bot_token`.
- **Admin**: JWT с коротким сроком жизни (15 минут) + refresh token; обязательная 2FA для super-admin.
- **Bot**: `bot_token` хранится в секретах (Vault / k8s secrets), никогда в коде.

## Authorization

- RBAC: `super_admin`, `support_admin`, `analyst`, `user`, `banned`.
- Все админские эндпоинты проверяют роль через декоратор.

## Rate Limiting

| Audience | Per hour | Per day |
|----------|----------|---------|
| Free user | 10 requests | 5 images, 2 videos |
| Premium | 100 requests | 50 images, 20 videos |
| Anonymous | 5 requests | — |

Реализация через `slowapi` + Redis.

## Data Protection

- TLS 1.2+ обязательно.
- Поля с чувствительными данными (`payment_id`, telegram fields) шифруются на уровне приложения для холодных бэкапов.
- Резервные копии БД — раз в сутки, шифрованные, retention 30 дней.

## Compliance

- GDPR: эндпоинт `DELETE /user/me` с экспортом данных и удалением.
- Telegram ToS: запрещенный контент фильтруется через preflight классификатор.

## Payments

- Idempotency keys для `successful_payment` (повторные webhook не начисляют дважды).
- Полный аудит каждой транзакции (`transactions` + `audit_log`).
- Возврат токенов возможен только через CRM с указанием причины.

## Telegram Bot Security

- Webhook secret token валидируется на каждом запросе.
- Ограничение по типам контента (антиспам, антифишинг).
- Anti-flood защита на уровне Telegram + Redis.

## Vulnerability Management

- Dependabot + GitHub Security Alerts.
- Регулярные `pip-audit` / `npm audit` в CI.
- Pre-commit hook: `gitleaks` для секретов.
- Перед каждым релизом — security review (см. checklist в issue Phase 4).
