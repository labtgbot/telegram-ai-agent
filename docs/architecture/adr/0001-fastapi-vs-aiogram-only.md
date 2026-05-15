# ADR-0001: Backend на FastAPI + aiogram в едином процессе

- **Статус**: Accepted
- **Дата**: 2026-05-15
- **Авторы**: @konard
- **Связанные документы**: [issue #3](https://github.com/labtgbot/telegram-ai-agent/issues/3), [C4 Container](../diagrams/c4-container.md), [C4 Component](../diagrams/c4-component.md)

## Контекст

Telegram AI Agent должен одновременно:

1. Обслуживать webhook'и Telegram (`bot updates`, `successful_payment`).
2. Отдавать REST API для Mini App (React) и Admin CRM (Next.js).
3. Принимать оплаты Telegram Stars и хранить транзакции.
4. Делиться единой бизнес-логикой (token service, payment service, rate limiter, audit log).

Возможны два принципиальных варианта раскладки backend:

- **A**: только `aiogram` в long-polling или webhook режиме, REST дописать на встроенном `aiohttp` (на котором уже работает aiogram).
- **B**: `FastAPI` для REST + `aiogram` для обработки Telegram, оба в одном Python-процессе, общий event loop и DI-контейнер.
- **C**: разнести в два сервиса: чистый `aiogram`-бот и отдельный FastAPI-API. Общение — внутренний HTTP/RPC.

## Рассмотренные варианты

### Вариант A — только aiogram (aiohttp REST)
- Плюсы: единая зависимость, простой деплой.
- Минусы: aiohttp REST в 2026 проигрывает FastAPI по DX (нет автогенерации OpenAPI, ограниченная экосистема dependency-injection, слабая валидация без pydantic v2). Mini App и CRM хотят полноценный OpenAPI для генерации клиентов.

### Вариант B — FastAPI + aiogram в одном процессе
- Плюсы:
  - FastAPI даёт автогенерируемый OpenAPI (`/docs`) для Mini App/CRM и встроенную валидацию pydantic v2.
  - aiogram 3 нативно поддерживает интеграцию с ASGI (`fastapi-users`, `aiogram.webhook.aiohttp_server` и собственный `SimpleRequestHandler` для FastAPI).
  - Общий event loop, общая DI-инфраструктура (`Depends`), общие модели и сервисы — нет дублирования.
  - Один Docker-образ, один деплой, одна точка наблюдаемости (`/metrics`).
- Минусы:
  - Один процесс — общий blast radius: бага в REST роутах может зацепить обработку бота. Митигируется тестами и хорошей структурой (см. C4 Component).
  - При взрывном росте трафика придётся делить — но это вопрос Phase 4, не Phase 1.

### Вариант C — два сервиса (bot и api отдельно)
- Плюсы: жёсткая изоляция, независимое масштабирование.
- Минусы: дублирование DI/моделей или внутренний RPC (лишняя сложность), два деплоя, два набора метрик. Преждевременная оптимизация на MVP стадии.

## Решение

Принят **Вариант B**: FastAPI + aiogram в одном процессе, один Docker-образ. Маршруты бота монтируются как ASGI-роутер внутри FastAPI приложения.

Структура каталогов:

```
backend/app/
  api/           # FastAPI routers
  bot/           # aiogram routers и middlewares
  services/     # бизнес-логика, общая для api/ и bot/
  repositories/  # SQLAlchemy
  core/         # config, security, di
```

## Последствия

**Положительные**
- Минимальный operational overhead для Phase 1–3.
- OpenAPI генерируется автоматически — Mini App и CRM получают типизированные клиенты.
- Один путь для миграций, конфигурации, мониторинга.

**Отрицательные / компромиссы**
- Общий процесс: при сбое падают и REST, и бот. Митигируем readiness probe и HPA с минимум 2 репликами в production.
- Если бот станет CPU-bound (например, валидация больших файлов), может понадобиться выделить отдельный pod — это будет отдельный ADR в Phase 4.

**Out of scope**
- Перенос long-polling бота на собственный сервис (не нужно — webhook покрывает MVP).

## Метрики успеха

- Время холодного старта pod'а ≤ 5 сек.
- p95 REST-latency ≤ 200 мс при 50 RPS.
- Обработка webhook ≤ 100 мс p95.
- В Sentry нет ошибок вида «REST задержал event loop бота».
