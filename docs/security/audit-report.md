# Security Audit Report — Phase 4

Документ агрегирует все находки внутреннего security-аудита перед запуском
Telegram AI Agent (issue #34). Дополняет:

- [`threat-model.md`](threat-model.md) — STRIDE-таблица угроз.
- [`owasp-top10.md`](owasp-top10.md) — соответствие OWASP Top-10.
- [`pentest-scope.md`](pentest-scope.md) — план ручного пентеста.
- [`../SECURITY.md`](../SECURITY.md) — практики безопасности.
- [`../../SECURITY.md`](../../SECURITY.md) — responsible disclosure policy.

---

## 1. Методология

| Источник | Покрытие |
|----------|----------|
| `pip-audit` | Python-зависимости (PyPI + лок-файл `backend/pyproject.toml`) |
| `npm audit --omit=dev` | JS-зависимости production (`mini-app/`, `admin-dashboard/`) |
| `trivy fs` | Файлы репозитория (lockfile-ы + Dockerfile-ы) |
| `trivy image` | Финальные образы `tgai-backend`, `tgai-mini-app`, `tgai-admin` |
| `bandit -r backend/app` | SAST Python |
| `semgrep --config=p/owasp-top-ten --config=p/python --config=p/javascript` | SAST cross-language |
| `gitleaks detect` | Поиск секретов в истории Git |
| Manual review | STRIDE-таблицы (`threat-model.md`), code review критичных модулей |

Все сканеры запускаются в [`.github/workflows/security.yml`](../../.github/workflows/security.yml)
на каждом PR и на `push: main`. Failure любого job-а блокирует merge через
branch protection.

CVSS-оценка для внутренних находок выставлена на основе CVSS v3.1 calculator
(см. ссылки в каждой находке).

## 2. Шкала приоритета

| Уровень | Описание | SLA устранения |
|---------|----------|----------------|
| **P0** | Доступ к деньгам / админу / массовой PII, удалённое RCE | блокирует релиз, < 24h |
| **P1** | Компрометация аккаунта пользователя, sustained DoS, persistent XSS | блокирует релиз, < 72h |
| **P2** | Раскрытие неконфиденциальных данных, ratelimit-bypass | < 30 дней |
| **P3** | Информационная, hardening | < 90 дней |

## 3. Сводка находок

| ID | Заголовок | Приоритет | Статус |
|----|-----------|-----------|--------|
| F-001 | Дефолтный `ADMIN_JWT_SECRET=change-me` пропускается в non-dev окружения | P1 | ✅ resolved |
| F-002 | Отсутствует автоматический CI-сканер секретов (gitleaks) | P2 | ✅ resolved |
| F-003 | Нет prompt-output filter для ответов LLM | P2 | ⚠️ accepted (residual) |
| F-004 | Swagger UI / `/docs` доступен в production без RBAC | P2 | 🛠 planned (Phase 4.x) |
| F-005 | Logout не инвалидирует существующий access-token | P2 | 🛠 planned (Phase 4.x) |

Итого: **0 open P0/P1**, 2 open P2 с roadmap, 1 принятый остаточный риск
с компенсирующими мерами. Релиз `v1.0.0` разблокирован.

---

## 4. Детальные находки

### F-001 — Placeholder `ADMIN_JWT_SECRET` принимался в production

- **Категория:** OWASP A02 / A05 — Cryptographic Failures + Security
  Misconfiguration.
- **Серьёзность:** P1 (CVSS 8.1 — High; AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:N).
- **Угроза:** в `backend/app/core/config.py` поле `admin_jwt_secret` имело
  дефолт `"change-me"`. Если оператор забывал переопределить переменную при
  деплое, JWT-токены подписывались известным секретом, и любой внешний
  актор мог выпустить себе токен любого `role`, включая `super_admin`,
  обойдя 2FA.
- **Воспроизведение (PoC):** на staging стенде с дефолтом —
  ```python
  import jwt
  jwt.encode(
      {"sub": "1", "role": "super_admin", "type": "access",
       "iat": 0, "exp": 9999999999, "jti": "x"},
      "change-me", algorithm="HS256",
  )
  ```
  Токен принимается `get_current_admin`.
- **Меры (resolved):**
  1. `Settings.assert_production_safe()` отказывает в старте, если в
     `app_env in {staging, production, ...}` значение секрета равно
     placeholder или пустой строке (`backend/app/core/config.py`).
  2. Вызывается в `lifespan()` до того, как FastAPI начнёт принимать запросы
     (`backend/app/main.py`).
  3. Тесты-регрессии: `backend/tests/test_config.py::test_assert_production_safe_*`.
- **Подтверждение:** unit-тесты зелёные; запуск `APP_ENV=production
  ADMIN_JWT_SECRET=change-me uvicorn app.main:app` падает с
  `InsecureDefaultSecretError` до bind на порт.

### F-002 — Отсутствовал автоматический secrets-scanner

- **Категория:** OWASP A05 — Security Misconfiguration / Supply chain.
- **Серьёзность:** P2 (CVSS 5.3 — Medium; AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:N/A:N).
- **Угроза:** Хотя в репозитории не было секретов, для будущих коммитов
  не было «защёлки» — секрет, случайно добавленный разработчиком, остался
  бы в истории и при ротации был бы доступен в Git log.
- **Меры (resolved):**
  1. Добавлен job `gitleaks` в `.github/workflows/security.yml` —
     запускается на каждый PR и push, с `--redact` и проверкой полной
     истории (`--no-banner --log-opts=--all`).
  2. Конфиг `.gitleaks.toml` исключает фикстуры из `*/tests/` и
     `docker/compose.yml` (там — заведомо мок-значения).
  3. README обновлён ссылкой на политику disclosure (`SECURITY.md`).
- **Подтверждение:** CI gate активен; локально `gitleaks detect --source .`
  возвращает `no leaks found`.

### F-003 — Нет output-filter для ответов LLM (prompt-injection)

- **Категория:** OWASP A03 — Injection (LLM01:2023 Prompt Injection).
- **Серьёзность:** P2 (CVSS 4.3 — Medium; AV:N/AC:H/PR:L/UI:R/S:U/C:L/I:L/A:N).
- **Угроза:** Злоумышленник через пользовательский ввод заставляет LLM
  раскрыть содержимое системного промпта или включить инструкции из
  чужих документов. Поскольку:
  - системный промпт **не содержит** секретов, ключей, PII;
  - backend не имеет tool-calls, дающих LLM прямого доступа к БД;
  - Composio whitelist toolkits ограничивает доступные интеграции —
  риск ограничен «утечкой шаблона промпта» и социнженерной составляющей.
- **Меры (accepted residual):**
  1. Системные промпты регулярно ревьюятся (см. `docs/PRODUCT_VISION.md` §
     content guardrails).
  2. Ответы AI вёрстаются на frontend без `dangerouslySetInnerHTML` (XSS
     mitigation).
  3. Sentry breadcrumb прячет содержимое промпта (`send_default_pii=False`).
  4. Дальнейшие шаги (Phase 5+): добавить classifier-based output guard
     поверх `services/composio/postprocess.py`.
- **Принят:** maintainer-ы (см. ADR-черновик в commit-сообщении PR #81).

### F-004 — Swagger UI `/docs` доступен в production без RBAC

- **Категория:** OWASP A05 — Security Misconfiguration.
- **Серьёзность:** P2 (CVSS 4.3 — Medium; AV:N/AC:L/PR:N/UI:N/S:U/C:L/I:N/A:N).
- **Угроза:** Полная схема API доступна без авторизации в production,
  упрощает разведку перед атакой.
- **Меры (planned):**
  1. В Phase 4.x добавить middleware, которое отдаёт `/docs`, `/redoc`,
     `/openapi.json` только при наличии валидного `super_admin` JWT.
  2. Альтернатива: отдавать 404 если `app_env in {production}` и нет
     заголовка с pen-test engagement id.
  3. Tracking issue: создаётся при merge PR #81.
- **Митигация до фикса:** ingress уже скрывает `/docs` за IP-allowlist
  в staging; production-релиз пройдёт через `helm upgrade` с переменной
  `APP_DEBUG=false` и закрытым LoadBalancer для `/docs/*` на уровне
  Caddyfile (`docker/Caddyfile.prod`).

### F-005 — Logout не инвалидирует существующий access-token

- **Категория:** OWASP A07 — Identification and Authentication Failures.
- **Серьёзность:** P2 (CVSS 3.7 — Low; AV:N/AC:H/PR:N/UI:R/S:U/C:L/I:N/A:N).
- **Угроза:** При компрометации access-token (украденный с устройства
  админа) revocation возможна только через ban пользователя; токен живёт до
  `exp` (15 минут).
- **Меры (planned):**
  1. Добавить deny-list `jti` в Redis с TTL = `admin_access_token_ttl`.
  2. `get_current_admin` проверяет `jti` против Redis перед выдачей
     запроса.
  3. Endpoint `POST /api/v1/auth/admin/logout` добавляет `jti` в deny-list.
  4. Tracking issue: создаётся при merge PR #81.
- **Митигация до фикса:** TTL access-токена — 15 минут. Refresh rotation
  на каждом `POST /auth/admin/refresh` гарантирует, что украденный
  refresh-token идентифицируется при следующем легитимном refresh.

---

## 5. Результаты автоматических сканеров

Запуск сканеров встроен в [`.github/workflows/security.yml`](../../.github/workflows/security.yml).
Сводка на момент написания (commit см. в PR #81):

| Сканер | Сектор | Найдено P0/P1 | Найдено P2 | Найдено P3 |
|--------|--------|---------------|------------|------------|
| `pip-audit` | backend | 0 | 0 | 0 |
| `npm audit --omit=dev` (mini-app) | frontend | 0 | 0 | 0 |
| `npm audit --omit=dev` (admin-dashboard) | frontend | 0 | 0 | 0 |
| `trivy fs` | repo | 0 | 0 | 0 |
| `trivy image` (backend) | runtime | 0 | 0 | 0 |
| `trivy image` (mini-app) | runtime | 0 | 0 | 0 |
| `trivy image` (admin) | runtime | 0 | 0 | 0 |
| `bandit` | backend | 0 | 0 | 0 |
| `semgrep` (OWASP top 10) | repo | 0 | 0 | 0 |
| `gitleaks` | repo history | 0 | 0 | 0 |

Артефакты каждого запуска (SARIF + JSON) сохраняются в `actions/upload-artifact`
и доступны через GitHub UI 90 дней.

## 6. Ручной пентест

Скоуп — [`pentest-scope.md`](pentest-scope.md). На момент аудита
ручной пентест **запланирован**: будет выполнен внешней командой после
merge PR #81 и развёртывания staging-окружения `tgai-pentest`.

Финальный отчёт пентест-команды будет добавлен в этот документ разделом
«§ 7. External Penetration Test Report» с приложением CVSSv3 для каждой
находки и письменным re-test certificate.

## 7. Контакты и эскалация

- Maintainer security-pipeline-а: `@konard` (см. CODEOWNERS).
- Канал ответственного раскрытия — `mailto:security@labtgbot.example`
  (см. [`../../SECURITY.md`](../../SECURITY.md)).
- SLA подтверждения отчёта: 2 рабочих дня.
