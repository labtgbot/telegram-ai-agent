# Аудит issue #218 — раунд 3

Дата: 2026-06-13

Третий сквозной аудит логики Telegram AI Agent после закрытия предыдущих
наборов findings (`docs/audit/README.md` — раунд 1, issues `#138-#172`;
`docs/audit/issue-206/README.md` — раунд 2, issues `#208-#212`). Цель — найти
не продублированные дефекты (включая дефекты, внесённые remediation-PR
предыдущих раундов), и оформить их как отдельные профессиональные задачи с
labels и stage.

Сводный трекинг-EPIC: [#250](https://github.com/labtgbot/telegram-ai-agent/issues/250)
(группирует все 30 задач по стадиям). Tracking issue: [#218](https://github.com/labtgbot/telegram-ai-agent/issues/218).

## Методика

- Проверены открытые и закрытые issues, чтобы не создавать дубли.
- Каждой подсистеме (AI-сервисы и Composio, admin API и dashboard, mini-app,
  auth/session/RBAC/TOTP, rate-limit/webhook/bot, token economy,
  payments/subscriptions, data/migrations/GDPR, devops/CI) выделен отдельный
  проход по фактическому коду.
- Каждая ключевая находка перепроверена вручную по конкретным файлам и строкам.
- Для каждой находки указаны файлы и строки, механизм, влияние, stage, labels
  и acceptance criteria.

## Findings

| ID | Finding | Severity | Stage | GitHub issue |
| --- | --- | --- | --- | --- |
| 218-01 | Видео-джобы без `provider_job_id` или с постоянной ошибкой провайдера никогда не достигают терминального статуса и не возвращают токены | High | Stage 1 | [#220](https://github.com/labtgbot/telegram-ai-agent/issues/220) |
| 218-02 | Rate limiter: неатомарный check-then-record (TOCTOU) допускает превышение квоты при конкуренции | High | Stage 1 | [#221](https://github.com/labtgbot/telegram-ai-agent/issues/221) |
| 218-03 | Webhook claim-before-process: сбой commit/dispatch теряет side-effects навсегда и не освобождает Redis-claim | High | Stage 1 | [#222](https://github.com/labtgbot/telegram-ai-agent/issues/222) |
| 218-04 | `APP_DEBUG=true` отдаёт одноразовый admin login code в HTTP-ответе; нет production-guard; `.env.example` поставляет `APP_DEBUG=true` | High | Stage 1 | [#223](https://github.com/labtgbot/telegram-ai-agent/issues/223) |
| 218-05 | Backend admin endpoints требуют только «is admin», а dashboard гейтит `/users` до `support_admin` → analyst читает PII/CSV напрямую | Medium | Stage 2 | [#224](https://github.com/labtgbot/telegram-ai-agent/issues/224) |
| 218-06 | Composio client ретраит истёкший по таймауту POST `/tools/execute` → дублирующие провайдер-side выполнения для не-идемпотентных тулкитов | Medium | Stage 2 | [#225](https://github.com/labtgbot/telegram-ai-agent/issues/225) |
| 218-07 | Лимит длительности/размера voice `audio_url` задекларирован, но не проверяется (проверяется только base64-путь) | Medium | Stage 2 | [#226](https://github.com/labtgbot/telegram-ai-agent/issues/226) |
| 218-08 | Mini-app: нет React error boundary / router `errorElement` → падение lazy-chunk или render обнуляет весь экран | Medium | Stage 2 | [#227](https://github.com/labtgbot/telegram-ai-agent/issues/227) |
| 218-09 | Mini-app `HistoryPage`: гонка stale-response в fetch-эффекте (нет abort/ignore-guard) | Medium | Stage 2 | [#228](https://github.com/labtgbot/telegram-ai-agent/issues/228) |
| 218-10 | Subscription renewal worker ловит только `UserNotFoundError`, но не `IntegrityError` на дублирующем renewal-marker → падение батча и частичное продление | Medium | Stage 2 | [#229](https://github.com/labtgbot/telegram-ai-agent/issues/229) |
| 218-11 | Daily-bonus: streak-кэш пишется после `flush`, но до внешнего commit → при rollback ложный `AlreadyClaimed` и рассинхрон streak | Medium | Stage 2 | [#230](https://github.com/labtgbot/telegram-ai-agent/issues/230) |
| 218-12 | CSV-export proxy-routes проверяют только наличие токена; middleware по умолчанию `analyst` | Low | Stage 3 | [#231](https://github.com/labtgbot/telegram-ai-agent/issues/231) |
| 218-13 | Нет CSRF-защиты на admin auth route handlers (форс-logout/refresh через cross-site top-level POST, SameSite=lax) | Low | Stage 3 | [#232](https://github.com/labtgbot/telegram-ai-agent/issues/232) |
| 218-14 | `ASSIGNABLE_ROLES` содержит `Role.USER`, но docstring заявляет обратное (расхождение кода и комментария) | Low | Stage 3 | [#233](https://github.com/labtgbot/telegram-ai-agent/issues/233) |
| 218-15 | Сохранённый admin-контент (prompt templates/FAQ/welcome) не HTML-санитизируется → латентный stored XSS при появлении render-sink | Low | Stage 3 | [#234](https://github.com/labtgbot/telegram-ai-agent/issues/234) |
| 218-16 | Composio config хранится без ограничений (любой dict) и возвращается analyst через GET `/composio` → латентное раскрытие секретов | Low | Stage 3 | [#235](https://github.com/labtgbot/telegram-ai-agent/issues/235) |
| 218-17 | Mini-app: `URL.createObjectURL` превью никогда не revoke → утечка памяти | Low | Stage 3 | [#236](https://github.com/labtgbot/telegram-ai-agent/issues/236) |
| 218-18 | Mini-app: `AbortController` сохраняется, но `.abort()` не вызывается → streaming fetch не отменяется при unmount | Low | Stage 3 | [#237](https://github.com/labtgbot/telegram-ai-agent/issues/237) |
| 218-19 | SSE start-event: расхождение поля `request_id` (backend) vs `requestId` (frontend); тест закрепляет неверный контракт | Low | Stage 3 | [#238](https://github.com/labtgbot/telegram-ai-agent/issues/238) |
| 218-20 | Admin login: code потребляется до TOTP-гейта → одна ошибка TOTP заставляет запрашивать новый code (grief/DoS для super_admin) | Low | Stage 3 | [#239](https://github.com/labtgbot/telegram-ai-agent/issues/239) |
| 218-21 | `admin_refresh_sessions` не имеет retention/cleanup → таблица растёт неограниченно | Low | Stage 3 | [#240](https://github.com/labtgbot/telegram-ai-agent/issues/240) |
| 218-22 | Bot: квота генерации списывается до guard на `composio is None` → сжигает квоту на выключенной фиче | Low | Stage 3 | [#241](https://github.com/labtgbot/telegram-ai-agent/issues/241) |
| 218-23 | Client-IP resolver возвращает левый (спуфабельный) XFF-элемент, когда все хопы доверенные | Low | Stage 3 | [#242](https://github.com/labtgbot/telegram-ai-agent/issues/242) |
| 218-24 | `TokenService.spend()` не усекает `composio_tool`/`mcp_server` до 255 (сейчас недостижимо, robustness-долг) | Low | Stage 3 | [#243](https://github.com/labtgbot/telegram-ai-agent/issues/243) |
| 218-25 | Дублирующий payment webhook возвращает `is_subscription=is_recurring` вместо `package.is_subscription` → неверный premium-UX при redelivery | Low | Stage 3 | [#244](https://github.com/labtgbot/telegram-ai-agent/issues/244) |
| 218-26 | `AdminSetting.updated_by` хранит user id без FK на `users.id` → orphaned refs, GDPR-анонимизация не очищает | Low | Stage 3 | [#245](https://github.com/labtgbot/telegram-ai-agent/issues/245) |
| 218-27 | `ChatMessage.user_id` денормализован от `thread.user_id` без CHECK/guard; data-export читает его напрямую | Low | Stage 3 | [#246](https://github.com/labtgbot/telegram-ai-agent/issues/246) |
| 218-28 | `Broadcast.status`/`audience` и `BroadcastRecipient.status` без CHECK-constraints при наличии справочников значений | Low | Stage 3 | [#247](https://github.com/labtgbot/telegram-ai-agent/issues/247) |
| 218-29 | CI: несогласованные pinned-версии `actions/checkout` (v4 в load-smoke/e2e vs v6 в остальных) | Low | Stage 3 | [#248](https://github.com/labtgbot/telegram-ai-agent/issues/248) |
| 218-30 | Образы инфра-сервисов закреплены по version-only тегам (`caddy:2.8-alpine`, `postgres:15-alpine`, `redis:7-alpine`) → недетерминированные обновления | Low | Stage 3 | [#249](https://github.com/labtgbot/telegram-ai-agent/issues/249) |

Подробности — в каталоге [`findings/`](findings/).

## Не дублирует предыдущие аудиты

Раунды 1-2 уже покрыли: hardcoded JWT secret (#138), partition exhaustion
(#139), per-user rate-limit bypass (#140), webhook secret guard (#141), bot
rate-limit bypass (#142), XFF trust (#143), GDPR batch rollback (#144), stale
balance cache после покупки (#145), payment-idempotency drift (#146), broken
mini-app routes (#147), compose hardening (#148), trivyignore (#149), admin
brute-force (#150), CSV injection (#151), initData query leak (#152), analyst
audit-log access (#153), concurrent daily-bonus 500 (#154), write-through
balance cache (#155), generation TOCTOU (#156), broadcast claiming (#157),
webhook update_id idempotency (#158), broadcast backoff (#159), open redirect
(#160), middleware role map (#161), admin token payload validation (#162),
swallowed API errors (#163), balance refresh (#164), alembic partition guard
(#165), secret-scan gaps (#166), monitoring defaults (#167), auth hardening +
admin enumeration (#168), middleware headers leak (#169), redundant indexes /
FK (#170), retries 4xx / source maps (#171), CI supply-chain (#172), Composio
production mock (#208), workers unwired (#209), admin API localhost (#210),
refresh-token replay (#211), age verification docs (#212).

Текущие 30 findings проверены отдельно и не совпадают с этими задачами; часть
из них (218-03, 218-23) — это дефекты, внесённые/оставшиеся после remediation
предыдущих раундов (#158, #143 соответственно).

## Рекомендованный порядок

1. **Stage 1 (High):** 218-01, 218-02, 218-03, 218-04 — экономическая
   целостность токенов, обход квот, потеря событий и утечка login-кода.
2. **Stage 2 (Medium):** 218-05 … 218-11 — RBAC-зазор, идемпотентность
   провайдера, корректность mini-app и token/payment-флоу.
3. **Stage 3 (Low):** 218-12 … 218-30 — defence-in-depth, гигиена схемы,
   утечки памяти, документация и CI/инфра-pinning.
