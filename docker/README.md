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

## Production-like Compose

`compose.prod.yml` intentionally fails fast when release image references or
secrets are missing. Set explicit `BACKEND_IMAGE`, `MINI_APP_IMAGE`,
`ADMIN_IMAGE`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `COMPOSIO_API_KEY`,
`CADDY_DATA_DIR`, and `CADDY_CONFIG_DIR` in `.env.prod`.

The production-like stack starts the backend API plus background worker
services from the same backend image:

- `broadcast-worker`: `python -m app.workers.broadcast --loop`
- `video-polling-worker`: `python -m app.workers.video_polling --loop --interval-s 10`
- `subscriptions-worker`: daily renewal loop
- `account-deletion-worker`: daily GDPR anonymisation loop
- `daily-analytics-worker`: daily analytics snapshot loop
- `token-usage-partitions-worker`: token usage partition maintenance loop

The Caddy directories must be writable by UID/GID `65534` because the
production-like stack runs Caddy as a non-root user:

```bash
sudo install -d -o 65534 -g 65534 -m 0750 /opt/telegram-ai-agent/caddy/data
sudo install -d -o 65534 -g 65534 -m 0750 /opt/telegram-ai-agent/caddy/config
```
