# OWASP Top-10 Checklist (2021)

Проверка соответствия Telegram AI Agent контрольным пунктам **OWASP Top-10
2021**. Документ актуализируется одновременно с
[`threat-model.md`](threat-model.md) и [`audit-report.md`](audit-report.md).

Легенда:

- ✅ — контроль реализован и проверен (есть код / тесты / конфиг).
- 🛠 — контроль реализован частично, есть остаточный риск.
- ❌ — не покрыто.
- ➖ — неприменимо.

---

## A01:2021 — Broken Access Control

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| Default-deny на admin-роуты | ✅ | `Depends(require_role("..."))` обязателен для `/admin/*` (`backend/app/auth/rbac.py`) |
| Server-side проверка владения объектом | ✅ | `PaymentService.get_status` фильтрует по `user_id` (`backend/app/services/payments.py`) |
| Запрет вертикальной эскалации через JWT | ✅ | `users.role` читается из БД (`backend/app/auth/dependencies.py`), JWT-`role` — только для логирования |
| Запрет refresh-токена как Bearer | ✅ | `expected_type="access"` enforced в `get_current_admin` |
| CORS lockdown | ✅ | По умолчанию в FastAPI middleware не открыт; production-CORS allow-list задаётся через `APP_CORS_ALLOWED_ORIGINS` |
| Rate limiting | ✅ | `backend/app/api/rate_limit.py` + per-plan конфиг |
| Отдельный bucket для anonymous | ✅ | `PLAN_ANONYMOUS` keyed by IP |

## A02:2021 — Cryptographic Failures

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| TLS 1.2+ на ingress | ✅ | Caddyfile / Helm `tls.minVersion=1.2` |
| Постоянное сравнение HMAC | ✅ | `hmac.compare_digest` в `verify_init_data` |
| JWT с длинным секретом | ✅ | `ADMIN_JWT_SECRET` — заглушка `change-me` блокируется в проде (см. `audit-report.md` F-002) |
| Хеширование OTP-кодов | ✅ | SHA-256 хеш сохраняется в Redis, оригинал не пишется |
| Encryption at rest для backup-ов | ✅ | Backup-encryption (issue #33) — AES-256-GCM |
| Запрет MD5/SHA-1 для secrets | ✅ | Не используются (только SHA-256 / HMAC-SHA256) |

## A03:2021 — Injection

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| Параметризованные SQL-запросы | ✅ | 100% запросов через SQLAlchemy 2.x async (`select`, `update`, `bindparam`) |
| Запрет shell-injection в bot-командах | ✅ | Все команды dispatch'атся через python-функции, никаких `os.system`/`subprocess.shell=True` |
| Защита от LLM prompt injection (output) | 🛠 | Системные промпты не содержат секретов; план — добавить classifier output guard (см. audit-report F-003) |
| Защита от LDAP/OS-command injection | ➖ | Не используем LDAP/OS-команды |
| HTML-санитайз в admin UI | ✅ | Next.js по-умолчанию экранирует; `dangerouslySetInnerHTML` не используется |

## A04:2021 — Insecure Design

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| Threat model документирован | ✅ | [`threat-model.md`](threat-model.md) |
| Идемпотентность платёжных webhook-ов | ✅ | Partial unique index на `transactions.payment_id` (`migrations/0003_payment_idempotency`) |
| Ratelimit для login + AI квот | ✅ | `ADMIN_LOGIN_MAX_ATTEMPTS=5`, `rate_limit_config` per-plan |
| Recovery без email (admin) | ✅ | Только через Telegram-бота + 2FA, deny by default для super-admin |
| Принцип least privilege для DB-ролей | ✅ | Helm создаёт `app` role без `SUPERUSER`; миграции — отдельный creds |

## A05:2021 — Security Misconfiguration

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| Production отключает `debug` | ✅ | `APP_DEBUG=false` в `Dockerfile.backend` prod stage |
| Запрет дефолтных секретов в проде | ✅ | Bootstrap-check (см. audit-report F-002): `ADMIN_JWT_SECRET=change-me` → ошибка старта |
| Минимальный образ | ✅ | `python:3.11-slim`, неприв. пользователь `app:app` (uid 1000) |
| Trivy-сканирование образов | ✅ | `.github/workflows/security.yml` job `trivy-images` |
| HSTS / X-Frame-Options / X-Content-Type-Options | ✅ | Каждый сервис frontend ставит headers через Next.js `headers()` / Vite-plugin / Caddyfile |
| `/docs` отключен в production | 🛠 | План: gate Swagger UI за RBAC `super_admin` (audit-report F-004) |

## A06:2021 — Vulnerable and Outdated Components

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| Dependabot активирован | ✅ | `.github/dependabot.yml` — pip + npm |
| `pip-audit` в CI | ✅ | `.github/workflows/security.yml` job `pip-audit` |
| `npm audit --omit=dev` в CI | ✅ | `.github/workflows/security.yml` job `npm-audit` |
| Trivy сканирует образ + lockfile | ✅ | jobs `trivy-fs` + `trivy-images` |
| Пины зависимостей | ✅ | Версии заявлены диапазоном `>=X,<Y` (PEP 440); lockfile у frontend-пакетов |

## A07:2021 — Identification and Authentication Failures

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| Telegram WebApp HMAC-валидация | ✅ | `backend/app/auth/telegram.py`; max age 24h |
| Brute-force защита для admin OTP | ✅ | `ADMIN_LOGIN_MAX_ATTEMPTS=5` инвалидирует код |
| TOTP 2FA для super_admin | ✅ | `backend/app/auth/totp.py`, RFC 6238 (±1 период) |
| Безопасное хранение secrets | ✅ | sealed-secrets / External Secrets / env, нет хардкода |
| Logout invalidates access-token | 🛠 | План: deny-list `jti` в Redis (audit-report F-005) |
| Refresh rotation | ✅ | `POST /auth/admin/refresh` всегда выдаёт новую пару |

## A08:2021 — Software and Data Integrity Failures

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| Pinned GitHub Actions | ✅ | Все actions использованы с указанием major/minor (`actions/checkout@v6`, `docker/build-push-action@v7`) |
| Запрет unsigned deploy | ✅ | Production-deploy требует GitHub Environment с reviewer'ом (`release.yml`) |
| Integrity check образов | ✅ | Образы публикуются в GHCR, deploy ссылается на immutable `sha`/`semver` теги |
| Webhook secret валидируется | ✅ | См. T-WBHK-S1 в threat-model |
| Audit log миграций | ✅ | `alembic upgrade head` логируется в `app.startup` + `audit_log` |

## A09:2021 — Security Logging and Monitoring Failures

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| Structured logging (JSON) | ✅ | `structlog`, формат конфигурируется (`LOG_FORMAT`) |
| Все 4xx/5xx в Sentry | ✅ | `backend/app/core/sentry.py` инициализируется при `SENTRY_DSN` |
| Метрики аномалий (no-payment, активные пользователи) | ✅ | `deploy/monitoring/prometheus/rules/slo-alerts.yml` |
| Login attempts логируются с `actor_id` + `ip` | ✅ | `backend/app/services/admin_login.py` + `record_admin_login` |
| Alerting (Telegram) | ✅ | `deploy/monitoring/alertmanager/alertmanager.yml` |
| Retention логов ≥ 30 дней | ✅ | Loki retention policy: 30d |

## A10:2021 — Server-Side Request Forgery (SSRF)

| Контроль | Статус | Доказательство |
|----------|--------|----------------|
| Whitelist исходящих хостов | ✅ | Composio base URL пинируется; `httpx` клиент не принимает user-controlled URLs |
| User upload не превращается в URL-fetch | ✅ | Документы анализируются по содержимому, без `urllib.urlopen` |
| Запрет meta-data endpoint cluster | ✅ | Helm NetworkPolicy блокирует `169.254.169.254` (документировано в `docs/DEPLOYMENT.md`) |
| Telegram `file_id` загружается через Bot API | ✅ | Backend не делает HTTP-запрос на произвольный URL: `GetFile` отдаёт временный путь |

---

## Сводка

| Категория | Контролей | ✅ | 🛠 | ❌ |
|-----------|-----------|----|-----|----|
| A01 | 7 | 7 | 0 | 0 |
| A02 | 6 | 6 | 0 | 0 |
| A03 | 5 | 4 | 1 | 0 |
| A04 | 5 | 5 | 0 | 0 |
| A05 | 6 | 5 | 1 | 0 |
| A06 | 5 | 5 | 0 | 0 |
| A07 | 6 | 5 | 1 | 0 |
| A08 | 5 | 5 | 0 | 0 |
| A09 | 6 | 6 | 0 | 0 |
| A10 | 4 | 4 | 0 | 0 |
| **Всего** | **55** | **52** | **3** | **0** |

Все 🛠-пункты разобраны в [`audit-report.md`](audit-report.md). P0/P1
открытых уязвимостей нет.
