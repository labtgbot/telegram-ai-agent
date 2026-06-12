# C4: Container Diagram

Контейнеры внутри границы Telegram AI Agent. Контейнер ≈ деплоится отдельно (процесс, сервис, БД).

```mermaid
C4Container
    title Container Diagram — Telegram AI Agent

    Person(user, "Пользователь")
    Person(admin, "Администратор / Саппорт")

    System_Boundary(tgaa, "Telegram AI Agent") {
        Container(bot_api, "Backend API + Bot", "Python 3.11, FastAPI, aiogram", "Webhook от Telegram, REST API для Mini App и CRM, обработка сообщений бота")
        Container(worker, "Background Workers", "Python 3.11, app.workers.*", "Рассылки, подписки, GDPR deletion, аналитика, polling видео")
        Container(scheduler, "Kubernetes CronJobs", "batch/v1 CronJob", "Периодические задачи: подписки, account deletion, daily analytics, partition maintenance")

        Container(mini_app, "Mini App", "React + TypeScript + Telegram WebApp SDK", "UI внутри Telegram: чат, баланс, покупка токенов")
        Container(admin_ui, "Admin CRM", "Next.js 14 + TypeScript", "Дашборд, управление пользователями, тарифами, рассылками")

        ContainerDb(postgres, "PostgreSQL", "PostgreSQL 15", "Пользователи, транзакции, аналитика, аудит")
        ContainerDb(redis, "Redis", "Redis 7", "Кэш, rate-limit окна, сессии")
    }

    System_Ext(telegram, "Telegram", "Bot API + Stars")
    System_Ext(composio, "Composio MCP")
    System_Ext(observ, "Prometheus / Grafana / Sentry")

    Rel(user, telegram, "Сообщения, оплата")
    Rel(user, mini_app, "Открывает внутри Telegram")
    Rel(admin, admin_ui, "HTTPS, JWT")

    Rel(telegram, bot_api, "Webhook updates, payment events", "HTTPS")
    Rel(bot_api, telegram, "Bot API", "HTTPS")

    Rel(mini_app, bot_api, "REST /api/v1", "HTTPS, initData header")
    Rel(admin_ui, bot_api, "REST /api/v1/admin", "HTTPS, JWT")

    Rel(bot_api, postgres, "SQLAlchemy + asyncpg", "TCP 5432")
    Rel(bot_api, redis, "redis-py", "TCP 6379")
    Rel(worker, redis, "Кэш / rate-limit config", "TCP 6379")
    Rel(worker, postgres, "SQLAlchemy", "TCP 5432")
    Rel(scheduler, postgres, "Запускает worker entrypoints")

    Rel(bot_api, composio, "AI запросы", "HTTPS")
    Rel(worker, composio, "Длительные AI задачи", "HTTPS")

    Rel(bot_api, observ, "Метрики /metrics, логи")
    Rel(worker, observ, "Метрики, логи")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="2")
```

## Контейнеры

| Контейнер | Технология | Деплой | Ответственность |
|-----------|-----------|--------|-----------------|
| Backend API + Bot | FastAPI + aiogram 3 | k8s deployment, 2+ реплики | HTTP + bot webhook + бизнес-логика |
| Background Workers | Python 3.11, `app.workers.*` | k8s Deployments + CronJobs | Фоновые задачи (рассылки, подписки, аналитика, видео polling) |
| Mini App          | React 18 + Vite     | k8s + nginx, CDN | UI внутри Telegram |
| Admin CRM         | Next.js 14          | k8s + nginx | Веб-админка |
| PostgreSQL        | PostgreSQL 15       | Managed / StatefulSet | Основное хранилище |
| Redis             | Redis 7             | Managed / StatefulSet | Кэш + rate-limit |

## Почему такие границы

- **Backend API + Bot единый контейнер**: см. [ADR-001](../adr/0001-fastapi-vs-aiogram-only.md). FastAPI и aiogram живут вместе в одном процессе ради REST-эндпоинтов Mini App и CRM, переиспользования сервисного слоя и единого Observability.
- **Workers вынесены отдельно**: тяжёлые и периодические задачи не должны блокировать обработку webhook.
- **Mini App и CRM деплоятся как статика**: упрощает CDN-кеширование и независимый релиз UI.
- **Redis несёт две роли**: кэш и sliding-window rate-limit. Допустимо благодаря низкой нагрузке на каждую из них; при росте можно разнести инстансы.

> Глубже: [Component Diagram](./c4-component.md), [ADR-003](../adr/0003-authentication-scheme.md), [ADR-004](../adr/0004-rate-limiting.md).
