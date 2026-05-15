# Backend

FastAPI приложение для Telegram AI Agent.

## Layout

```
backend/
├── app/
│   ├── api/         # HTTP REST endpoints
│   ├── bot/         # Telegram webhook + handlers
│   ├── crm/         # Admin endpoints
│   ├── models/      # SQLAlchemy ORM
│   ├── schemas/     # Pydantic схемы
│   ├── services/    # Бизнес-логика: tokens, payments, ai, broadcast
│   ├── core/        # Конфиг, безопасность, утилиты
│   └── main.py      # Entry point
├── alembic/         # Миграции
├── tests/
└── pyproject.toml
```

## Quickstart

> ⚠️ Заготовка. Реализация добавится по issue-задачам.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
```

## Testing

```bash
pytest -q
```

Подробности — в `docs/DEPLOYMENT.md`.
