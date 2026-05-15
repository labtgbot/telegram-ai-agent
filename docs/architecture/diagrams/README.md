# C4 Architecture Diagrams

Документация архитектуры Telegram AI Agent по нотации [C4 Model](https://c4model.com/).

Используется Mermaid (`C4Context`, `C4Container`, `C4Component`) — диаграммы рендерятся прямо в GitHub.

## Уровни

| Уровень | Файл | Описание |
|---------|------|----------|
| 1. Context   | [`c4-context.md`](./c4-context.md)     | Система в окружении пользователей и внешних сервисов |
| 2. Container | [`c4-container.md`](./c4-container.md) | Логические контейнеры (FastAPI, Redis, PostgreSQL, Mini App, CRM) |
| 3. Component | [`c4-component.md`](./c4-component.md) | Внутреннее устройство backend (handlers, services, repositories) |

> Дополнительная диаграмма потока данных и развертывания — в [`deployment.md`](./deployment.md).

## Соглашения

- Цвета задаются классами Mermaid: `external` — серый, `data` — синий, `ai` — фиолетовый.
- Имена контейнеров совпадают с директориями репозитория (`backend`, `mini-app`, `admin-dashboard`).
- Каждый ADR ссылается на диаграмму, к которой относится решение.
