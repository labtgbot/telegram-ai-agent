# Backend

FastAPI приложение для Telegram AI Agent.

## Layout

```
backend/
├── app/
│   ├── api/
│   │   └── v1/         # HTTP REST endpoints (включая /health)
│   ├── bot/            # Telegram webhook + handlers (Phase 2)
│   ├── crm/            # Admin endpoints (Phase 3)
│   ├── models/         # SQLAlchemy ORM
│   ├── schemas/        # Pydantic схемы (Phase 2)
│   ├── services/       # Бизнес-логика (Phase 2)
│   ├── core/           # config, database, redis, logging
│   └── main.py         # Entry point (FastAPI app)
├── alembic/            # Миграции
├── tests/
└── pyproject.toml
```

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

После старта откройте:

- <http://localhost:8000/> — корень.
- <http://localhost:8000/docs> — OpenAPI UI.
- <http://localhost:8000/api/v1/health> — проверка БД + Redis (200 / 503).
- <http://localhost:8000/api/v1/health/live> — liveness без I/O.

## Make-цели

```
make install    # установить backend в editable-режиме
make lint       # ruff check
make format     # ruff --fix + black
make typecheck  # mypy
make test       # pytest
make dev        # uvicorn --reload
make migrate    # alembic upgrade head
make seed       # python -m scripts.seed
```

## Переменные окружения

См. `.env.example`. Ключевые:

| Переменная | Назначение |
|------------|-----------|
| `APP_ENV` | `development` / `staging` / `production`. |
| `APP_DEBUG` | Включает дебаг-режим FastAPI. |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR`. |
| `LOG_FORMAT` | `json` (prod) или `console` (dev). |
| `DATABASE_URL` | URL для async SQLAlchemy (asyncpg). |
| `REDIS_URL` | URL Redis-кэша. |
| `API_V1_PREFIX` | Префикс v1 API (по умолчанию `/api/v1`). |
| `HEALTH_CHECK_TIMEOUT` | Per-dep таймаут (сек) для `/health`. |
| `TRUSTED_PROXY_IPS` | Comma-separated IP/CIDR allowlist of reverse proxies whose `X-Forwarded-For` headers are trusted. Empty means XFF is ignored. |

## Структурированное логирование

`structlog` настраивается через `app.core.logging.configure_logging`. В dev
выводится человекочитаемая консоль, в проде — JSON-строки, удобные для
log-агрегаторов (Loki, Datadog).

## Testing

```bash
pytest -q
```

Тесты, требующие живую БД, скипаются автоматически, если `DATABASE_URL` не
задан или БД недоступна. Подробности — в `docs/DEPLOYMENT.md`.
