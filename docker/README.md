# Docker

Файлы для контейнеризации:

- `Dockerfile.backend` — multi-stage образ (target `dev`, target `prod`).
- `Dockerfile.mini-app` — будет добавлен в Phase 2.
- `Dockerfile.admin` — будет добавлен в Phase 3.
- `compose.yml` — локальный стек: `backend` + `postgres` + `redis`.
- `compose.prod.yml` — production-like стек (Phase 4).

## Локальный запуск

```bash
docker compose -f docker/compose.yml up -d
docker compose -f docker/compose.yml logs -f backend
```

После старта приложение слушает на <http://localhost:8000>:

- Корневой маршрут: <http://localhost:8000/>
- OpenAPI UI: <http://localhost:8000/docs>
- Health-check: <http://localhost:8000/api/v1/health>

## Миграции

```bash
docker compose -f docker/compose.yml exec backend alembic upgrade head
```

## Сборка прод-образа

```bash
docker build -f docker/Dockerfile.backend --target prod -t tgai-backend:prod .
```
