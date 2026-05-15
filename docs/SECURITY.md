# Security Best Practices

## Authentication

- **User**: Telegram WebApp `initData` подписывается ботом, верификация HMAC по `bot_token`.
- **Admin**: JWT с коротким сроком жизни (15 минут) + refresh token; обязательная 2FA для super-admin.
- **Bot**: `bot_token` хранится в секретах (Vault / k8s secrets), никогда в коде.

### Telegram WebApp `initData`

Полная реализация — `backend/app/auth/telegram.py`. Алгоритм (см.
[Telegram docs](https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app)):

1. Берём query-string `initData`, отделяем поле `hash`.
2. Сортируем остальные пары по ключу и соединяем `\n` — получаем
   `data_check_string`.
3. `secret_key = HMAC_SHA256(bot_token, key="WebAppData")`.
4. `expected_hash = HMAC_SHA256(data_check_string, key=secret_key)`.
5. Сравниваем константно-временным `hmac.compare_digest` с присланным `hash`.
6. Проверяем, что `auth_date` не старше `TELEGRAM_INIT_DATA_MAX_AGE`
   (по умолчанию — 24 часа) — защита от replay-атак.

Эндпоинт `POST /api/v1/auth/telegram/verify` принимает заголовок
`X-Telegram-Init-Data` (или query-параметр `initData` для удобства
мини-приложений), создаёт пользователя при первом обращении (с
автогенерируемым `referral_code`) и возвращает актуальную запись.

### Admin Login

Двухшаговый flow с одноразовым кодом и опциональным TOTP (2FA):

1. `POST /api/v1/auth/admin/login/request` — `{telegram_id}`. Бэкенд
   генерирует 6-значный код, сохраняет SHA-256 хеш в Redis с TTL =
   `ADMIN_LOGIN_CODE_TTL` (5 минут по умолчанию). В production код
   доставляется через Telegram-бота. В dev-режиме код возвращается прямо в
   ответе (`delivery=response`), чтобы пройти e2e без бота.
2. `POST /api/v1/auth/admin/login/verify` — `{telegram_id, code, totp_code?}`.
   Бэкенд:
   - constant-time сравнивает хеш кода;
   - если код верный — удаляет ключ из Redis (single-use);
   - если у пользователя `role=super_admin` и `totp_enabled=true` — требует
     валидный TOTP;
   - возвращает пару `access_token` (15 мин) + `refresh_token` (7 дней).
3. После `ADMIN_LOGIN_MAX_ATTEMPTS` неверных попыток (по умолчанию 5)
   ключ удаляется, требуется повторный запрос кода (защита от brute force).

### JWT

- HS256 (по умолчанию), секрет — `ADMIN_JWT_SECRET`.
- Поля payload: `sub`, `role`, `type` (`access` или `refresh`), `iat`, `exp`, `jti`.
- `decode_token` различает `TokenExpiredError` (валидная подпись, истёкший
  `exp`) и `InvalidTokenError` (подпись/структура/тип).
- `POST /api/v1/auth/admin/refresh` принимает refresh-token и возвращает
  новую пару access+refresh. Refresh-токен **не** принимается в качестве
  Bearer для API-вызовов.

### TOTP (2FA)

- Стандарт RFC 6238, библиотека `pyotp`.
- 30-секундные периоды, 6-значные коды, ±1 период толерантности (clock skew).
- Секрет хранится в `users.totp_secret` (base32), флаг включения — в
  `users.totp_enabled`. Активируется отдельным административным действием
  (вне scope Phase 1 issue).

## Authorization

RBAC: `super_admin > support_admin > analyst > user > banned`.

- `app.auth.rbac.Role` — enum со значениями из колонки `users.role`.
- `require_role(*roles)` — FastAPI-зависимость:
  ```python
  @router.get("/admin/users", dependencies=[Depends(require_role("support_admin"))])
  async def list_users(): ...
  ```
  Проверка иерархическая — `super_admin` проходит везде, где требуется
  `support_admin` или `analyst`.
- `get_current_admin` — Bearer-аутентификация, проверяет роль ≥ `analyst`.
- `get_current_user_from_init_data` — валидация Telegram-сессии для
  user-эндпоинтов мини-апа.

## Rate Limiting

| Audience | Per hour | Per day |
|----------|----------|---------|
| Free user | 10 requests | 5 images, 2 videos |
| Premium | 100 requests | 50 images, 20 videos |
| Anonymous | 5 requests | — |

Реализация через `slowapi` + Redis (Phase 2).

Для admin-логина rate-limit уже встроен в код (`ADMIN_LOGIN_MAX_ATTEMPTS`
неверных попыток инвалидируют код).

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

## Конфигурация

| Переменная | По умолчанию | Назначение |
|------------|--------------|-----------|
| `TELEGRAM_BOT_TOKEN` | — | Источник HMAC-секрета для `initData`. |
| `TELEGRAM_INIT_DATA_MAX_AGE` | `86400` | Максимальный возраст `auth_date` (сек). |
| `ADMIN_JWT_SECRET` | `change-me` | Секрет HS256 для admin JWT. |
| `ADMIN_JWT_ALGORITHM` | `HS256` | Алгоритм подписи JWT. |
| `ADMIN_ACCESS_TOKEN_TTL` | `900` | TTL access-токена (сек). |
| `ADMIN_REFRESH_TOKEN_TTL` | `604800` | TTL refresh-токена (сек). |
| `ADMIN_LOGIN_CODE_TTL` | `300` | TTL одноразового кода (сек). |
| `ADMIN_LOGIN_CODE_LENGTH` | `6` | Длина кода (от 4 до 10). |
| `ADMIN_LOGIN_MAX_ATTEMPTS` | `5` | Лимит неверных попыток. |
| `ADMIN_SUPER_TELEGRAM_IDS` | пусто | Telegram-id, получающие `super_admin` при первом контакте. |
| `TOTP_ISSUER` | `Telegram AI Agent` | Метка issuer в TOTP-приложениях. |
