# Database Migrations (Alembic)

Конфигурация:

- `alembic.ini` — общие параметры (URL подменяется через `DATABASE_URL`).
- `alembic/env.py` — async engine, общий `Base.metadata`.
- `alembic/versions/` — миграции (по одной на изменение).

## Локальный запуск

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/telegram_ai_agent"
alembic upgrade head
```

Откатить одну миграцию:

```bash
alembic downgrade -1
```

## Соглашения

- Миграции пишутся вручную с использованием `autogenerate` как подсказки (см. [ADR-0005](../../docs/architecture/adr/0005-database-migrations.md)).
- Для разрушительных изменений используется правило **expand → migrate → contract**.
- Каждая миграция содержит рабочий `downgrade()`.

## Partitioning

Таблица `token_usage_logs` партиционирована `PARTITION BY RANGE (created_at)`.
Миграции создают партицию-«предохранитель» (DEFAULT) и стартовое окно
ежемесячных партиций. Новые партиции создаются ежемесячным заданием
`python -m app.workers.token_usage_partitions` (cron / k8s CronJob /
Celery beat) — см. ADR-0005 §Partitioning.
