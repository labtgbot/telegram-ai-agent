# Architecture Overview

Telegram AI Agent — конкурентный продукт на базе референса **Mira** с токеновой экономикой, ценообразованием на 50% дешевле аналогов и профессиональной CRM-системой.

## High-level Diagram

```mermaid
graph TB
    A[Telegram User] --> B[Telegram Bot API]
    A --> C[Mini App]
    B --> D[Backend FastAPI]
    C --> D
    D --> E[Token Manager]
    D --> F[Composio MCP]
    F --> G[Gemini / Claude / GPT]
    E --> H[(PostgreSQL)]
    E --> I[(Redis)]
    D --> J[Admin CRM Panel]
    J --> K[Analytics Dashboard]
    D --> L[Telegram Stars]
    L --> M[Stripe / TON]
```

## Components

| Component | Stack | Purpose |
|-----------|-------|---------|
| Backend API | FastAPI (Python 3.11+) | Telegram webhook, REST API, бизнес-логика |
| Database | PostgreSQL 15+ | Пользователи, транзакции, аналитика |
| Cache / Queue | Redis 7+ | Сессии, rate limit, celery broker |
| Task Queue | Celery | Платежные обработки, рассылки, фоновые задачи |
| Mini App | React + Telegram WebApp SDK | UI для пользователей внутри Telegram |
| Admin CRM | Next.js 14 + TypeScript | Управление проектом для администраторов |
| AI Provider | Composio MCP + Gemini/Claude/GPT | Генерация контента и текстовые запросы |
| Payments | Telegram Stars (+ optional TON / Stripe) | Прием оплат |
| Monitoring | Prometheus + Grafana | Метрики, дашборды, алерты |
| Deployment | Docker, Docker Compose, Kubernetes | Окружения и продакшн |

## Repository Layout

```
.
├── backend/             # FastAPI приложение
│   ├── app/
│   │   ├── api/         # REST endpoints
│   │   ├── bot/         # Telegram bot handlers
│   │   ├── crm/         # Admin endpoints
│   │   ├── models/      # SQLAlchemy модели
│   │   ├── services/    # Бизнес-логика (tokens, ai, payments)
│   │   └── core/        # Конфиг, безопасность, утилиты
│   ├── alembic/         # Миграции БД
│   └── tests/
├── mini-app/            # React Mini App
├── admin-dashboard/     # Next.js админка
├── docs/                # Документация
├── docker/              # Dockerfile и compose
├── .github/             # CI/CD, шаблоны
└── scripts/             # Утилиты (seed, бэкап и т.д.)
```

## Data Flow: Покупка токенов

1. Пользователь нажимает «Купить токены» в Mini App / боте.
2. Backend создает invoice через Telegram Stars API.
3. Telegram отправляет webhook `successful_payment` после оплаты.
4. Backend создает `transaction`, начисляет токены, обновляет баланс.
5. Аналитика обновляется (Prometheus + БД).

## Data Flow: Запрос к AI

1. Пользователь шлет запрос (текст, картинка, голос).
2. Backend проверяет баланс и rate limit.
3. Backend вызывает Composio MCP с нужным инструментом.
4. Composio проксирует запрос в Gemini/Claude/GPT.
5. Ответ возвращается пользователю, токены списываются, в `token_usage_logs` сохраняется запись.

## Security

- Telegram WebApp `initData` подпись для аутентификации пользователей.
- JWT для административных API (Admin CRM).
- Rate limiting через Redis (slowapi).
- Шифрование чувствительных данных в БД.
- Полный аудит-лог админских действий.

## Scalability

- Горизонтальное масштабирование backend через stateless API.
- Celery workers на отдельных подах.
- Кэш Redis для частых чтений (баланс, настройки).
- PostgreSQL: партиционирование `token_usage_logs` по дате.

Подробности по каждому компоненту — см. issue декомпозиции и документацию в `docs/`.
