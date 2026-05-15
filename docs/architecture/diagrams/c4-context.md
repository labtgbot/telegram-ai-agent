# C4: System Context

Telegram AI Agent в окружении пользователей и внешних систем.

```mermaid
C4Context
    title System Context — Telegram AI Agent

    Person(user, "Конечный пользователь", "Покупает токены, общается с ботом, использует Mini App")
    Person(admin, "Администратор", "Управляет ценообразованием, пользователями, аналитикой через CRM")
    Person(support, "Саппорт", "Просматривает обращения, начисляет компенсации, банит нарушителей")

    System(tgaa, "Telegram AI Agent", "Бот, Mini App и CRM с токеновой экономикой")

    System_Ext(telegram, "Telegram", "Bot API, Mini App WebApp, Stars Payments")
    System_Ext(composio, "Composio MCP", "Шлюз к LLM-провайдерам и инструментам")
    System_Ext(llms, "LLM Providers", "Gemini, Claude, GPT — через Composio")
    System_Ext(stripe, "Stripe / TON (опц.)", "Альтернативные платежные методы")
    System_Ext(observ, "Observability", "Prometheus, Grafana, Sentry")

    Rel(user, telegram, "Сообщения, оплата Stars, открытие Mini App")
    Rel(telegram, tgaa, "Webhook updates, successful_payment")
    Rel(tgaa, telegram, "sendMessage, createInvoiceLink, answerWebAppQuery")

    Rel(admin, tgaa, "Управление через CRM Dashboard (HTTPS, JWT)")
    Rel(support, tgaa, "Поддержка пользователей через CRM")

    Rel(tgaa, composio, "AI запросы: text/image/video/voice/search")
    Rel(composio, llms, "Проксирование к выбранному провайдеру")

    Rel(tgaa, stripe, "Платежные операции (опционально)")
    Rel(tgaa, observ, "Метрики, логи, алерты")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="2")
```

## Ключевые акторы

| Актор | Канал | Что делает |
|-------|-------|------------|
| Пользователь | Telegram (бот + Mini App) | Покупает токены, отправляет AI запросы |
| Администратор | Admin CRM (web) | Настраивает тарифы, рассылки, видит аналитику |
| Саппорт | Admin CRM (web) | Поддерживает пользователей |

## Внешние зависимости

- **Telegram Bot API** — единственная точка входа для пользователя. Авторизация через `initData` HMAC.
- **Composio MCP** — единый интерфейс к LLM-провайдерам, см. [ADR-002](../adr/0002-composio-mcp-vs-direct-sdk.md).
- **Stripe / TON** — опциональные платежные методы (только если Telegram Stars не покрывает регион).
- **Prometheus / Grafana / Sentry** — мониторинг и алертинг.

> Уровень детализации ниже: [Container Diagram](./c4-container.md).
