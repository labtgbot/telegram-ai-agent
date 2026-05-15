# ADR-0003: Схема аутентификации — Telegram WebApp initData + JWT для CRM

- **Статус**: Accepted
- **Дата**: 2026-05-15
- **Авторы**: @konard
- **Связанные документы**: [issue #3](https://github.com/labtgbot/telegram-ai-agent/issues/3), [SECURITY.md](../../SECURITY.md), [Telegram WebApp docs](https://core.telegram.org/bots/webapps#initializing-mini-apps)

## Контекст

У продукта три разных источника запросов с разной моделью доверия:

1. **Telegram Bot Webhook** — сам Telegram отправляет update'ы; нужно убедиться, что это не подделка.
2. **Mini App** — React внутри Telegram; пользователь не вводит пароль, идентичность нужно подтвердить через Telegram.
3. **Admin CRM** — отдельная веб-админка для администраторов и саппорта; полноценный логин с ролями (RBAC).

Унифицировать одной схемой нельзя: Mini App не имеет пароля, а CRM не доступна изнутри Telegram.

## Рассмотренные варианты

### A. Один JWT для всего (включая Mini App)
- Плюсы: одна реализация.
- Минусы: чтобы выдать JWT Mini App'у, всё равно нужна верификация Telegram initData. Лишний шаг и точка хранения токена в WebApp (`localStorage` или `sessionStorage`).

### B. Telegram initData для пользователя + JWT для админа
- Плюсы: каждая схема решает свою задачу. initData — нативная проверка Telegram, JWT — стандарт для веб-админок.
- Минусы: две кодовые ветки аутентификации. Митигируется отдельными FastAPI dependencies (`current_user`, `current_admin`).

### C. OAuth2 везде (через провайдера)
- Плюсы: единый стандарт.
- Минусы: внешний IdP для Telegram-пользователей избыточен и ломает UX внутри Telegram.

## Решение

Принят **Вариант B**. Три механизма аутентификации:

### 1. Telegram Webhook secret token
- При установке webhook задаётся `secret_token` ([Bot API](https://core.telegram.org/bots/api#setwebhook)).
- Каждый запрос от Telegram приходит с заголовком `X-Telegram-Bot-Api-Secret-Token` — сравниваем константно.
- Дополнительно проверяем `update_id` для защиты от replay.

### 2. Mini App — `initData` HMAC
- Mini App присылает заголовок `X-Telegram-Init-Data` с raw query string.
- Backend проверяет HMAC по схеме Telegram WebApp:
  1. Извлечь `hash` из initData.
  2. Построить `data_check_string` (отсортированные `key=value`, разделитель `\n`).
  3. `secret_key = HMAC_SHA256("WebAppData", bot_token)`.
  4. `expected_hash = HMAC_SHA256(secret_key, data_check_string)`.
  5. Сравнить с присланным `hash` константно.
  6. Проверить `auth_date` (не старше 24 часов).
- На основании initData backend получает `telegram_id` → `user` из БД.

### 3. Admin CRM — JWT с refresh + RBAC
- Логин администратора: email + пароль + TOTP 2FA (обязательная для `super_admin`).
- Access JWT: 15 минут, payload `{ sub: admin_id, role, jti }`.
- Refresh JWT: 7 дней, хранится `HttpOnly Secure SameSite=Strict` cookie.
- Алгоритм: `HS256` с секретом из k8s `Secret`.
- В payload включена роль; RBAC проверяется декоратором (`@requires("super_admin")`).
- При смене роли — все активные JWT инвалидируются (через `token_version` в БД и проверку в middleware).
- Все попытки логина пишутся в `audit_log`.

### 4. Сервис-к-сервису (внутренний)
- Celery worker'ы не имеют публичных эндпоинтов.
- Если потребуется внутренний RPC между сервисами в Phase 4 — отдельный mTLS / shared signing key (out of scope).

## Последствия

**Положительные**
- Каждая схема нативна для своей зоны: пользователь не вводит пароль, админ имеет 2FA, бот защищён secret token.
- RBAC реализуется одним декоратором, легко аудитировать.
- Logout / ротация секретов выполняются без перевыпуска клиентов Mini App.

**Отрицательные / компромиссы**
- Две схемы — две точки отказа. Митигируем тестами и явными dependencies в FastAPI.
- JWT в cookie упрощает CSRF-риск только при `SameSite=Strict`; для эндпоинтов с side-effects используем double-submit CSRF token.

**Безопасность по умолчанию**
- `bot_token`, `admin_jwt_secret`, hash паролей админов (`argon2id`) — только в k8s `Secret`.
- Ротация `bot_token` поддерживается без даунтайма: устанавливаем новый webhook, удаляем старый.
- Rate limit на логин админа: 5 попыток / 15 минут / IP (см. [ADR-0004](./0004-rate-limiting.md)).

**Out of scope**
- SSO для админки (Google Workspace) — рассмотрим в Phase 4.
- Биометрия / passkeys для пользователей — не требуется, Telegram уже доверенная среда.

## Метрики успеха

- 0 успешных запросов с невалидным `X-Telegram-Bot-Api-Secret-Token`.
- 0 успешных запросов в Mini App-эндпоинты с подделанным initData.
- Среднее время верификации initData ≤ 1 мс.
- 100% админских действий пишутся в `audit_log`.
- Неудачных попыток логина администратора > 10 за час → автоматический алёрт в Grafana.
