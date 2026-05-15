# Architecture Decision Records (ADR)

ADR — короткие документы, фиксирующие значимые архитектурные решения. Формат — упрощённый [adr-tools](https://github.com/npryce/adr-tools).

## Принципы

- Один ADR — одно решение.
- ADR неизменяем после `Accepted`. Замена — новый ADR со статусом `Supersedes ADR-XXXX`.
- Имя файла: `NNNN-короткое-имя.md`, нумерация подряд начиная с `0001`.

## Статусы

| Статус | Значение |
|--------|----------|
| `Proposed`  | Черновик, обсуждается |
| `Accepted`  | Принято, действует |
| `Deprecated`| Отменено без замены |
| `Superseded`| Заменено новым ADR (указать ссылку) |

## Шаблон

См. [`template.md`](./template.md).

## Реестр

| № | Решение | Статус | Дата |
|---|---------|--------|------|
| [ADR-0001](./0001-fastapi-vs-aiogram-only.md) | Backend: FastAPI + aiogram, единый процесс | Accepted | 2026-05-15 |
| [ADR-0002](./0002-composio-mcp-vs-direct-sdk.md) | Composio MCP как единый шлюз к LLM | Accepted | 2026-05-15 |
| [ADR-0003](./0003-authentication-scheme.md) | Telegram WebApp initData + JWT для CRM | Accepted | 2026-05-15 |
| [ADR-0004](./0004-rate-limiting.md) | Redis sliding-window для rate limiting | Accepted | 2026-05-15 |
| [ADR-0005](./0005-database-migrations.md) | Alembic + expand/contract миграции | Accepted | 2026-05-15 |
