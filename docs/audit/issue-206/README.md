# Аудит issue #206

Дата: 2026-06-12

Повторный аудит логики Telegram AI Agent после закрытия предыдущего набора
findings из `docs/audit/README.md`. Цель - найти не продублированные дефекты,
которые остались после закрытых issues/PRs, и оформить их как отдельные
профессиональные задачи с labels и stage.

## Методика

- Проверены открытые issues, чтобы не создавать дубли.
- Сопоставлены закрытые issues/PRs предыдущего аудита с текущим кодом.
- Повторно просмотрены зоны production configuration, Composio integration,
  workers/schedulers, admin dashboard deployment, admin auth refresh flow и
  public documentation.
- Для каждой находки указаны конкретные файлы и строки, ожидаемое влияние,
  stage, labels и acceptance criteria.

## Findings

| ID | Finding | Severity | Stage | Labels | GitHub issue |
| --- | --- | --- | --- | --- | --- |
| 206-01 | Production использует mock Composio без `COMPOSIO_API_KEY` | High | Stage 1 | `bug`, `backend`, `composio`, `ai-service`, `devops`, `stage-1-high`, `complexity-medium` | [#208](https://github.com/labtgbot/telegram-ai-agent/issues/208) |
| 206-02 | Background workers не развернуты и не запланированы в production | High | Stage 1 | `bug`, `backend`, `devops`, `architecture`, `telegram`, `payments`, `analytics`, `stage-1-high`, `complexity-high` | [#209](https://github.com/labtgbot/telegram-ai-agent/issues/209) |
| 206-03 | Admin dashboard по умолчанию обращается к localhost API в production | High | Stage 1 | `bug`, `admin-crm`, `devops`, `stage-1-high`, `complexity-medium` | [#210](https://github.com/labtgbot/telegram-ai-agent/issues/210) |
| 206-04 | Admin refresh tokens переиспользуются после rotation и logout | Medium | Stage 2 | `bug`, `backend`, `admin-crm`, `security`, `stage-2-medium`, `complexity-medium` | [#211](https://github.com/labtgbot/telegram-ai-agent/issues/211) |
| 206-05 | Документация age verification описывает несуществующий контракт | Low | Stage 3 | `bug`, `documentation`, `stage-3-low`, `complexity-low` | [#212](https://github.com/labtgbot/telegram-ai-agent/issues/212) |

Подробности:

- [206-01 Production Composio mock fallback](findings/01-composio-mock-production.md)
- [206-02 Production workers не подключены к deploy](findings/02-workers-unwired.md)
- [206-03 Admin API base URL указывает на localhost](findings/03-admin-api-base-url-localhost.md)
- [206-04 Refresh token replay после rotation/logout](findings/04-admin-refresh-token-replay.md)
- [206-05 Несовпадение документации age verification](findings/05-age-verification-docs-mismatch.md)

## Не дублирует предыдущий аудит

Предыдущий аудит `docs/audit/README.md` уже покрывал hardcoded JWT secret,
webhook secret guard, initData query leakage, admin route RBAC gaps,
admin token payload validation, broadcast row claiming/rate limits,
CSV injection, token usage partitions и несколько CI/devops hardening items.
Текущие findings проверены отдельно и не совпадают с закрытыми issues
`#138-#172` и PRs `#175-#205`.

## Рекомендованный порядок

1. Stage 1: закрыть production blockers `206-01`, `206-02`, `206-03`.
2. Stage 2: добавить серверную модель admin refresh sessions и revocation для
   `206-04`.
3. Stage 3: синхронизировать API/user/legal docs для `206-05`.
