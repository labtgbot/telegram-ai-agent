# Deployment Diagram

Развертывание Telegram AI Agent в production. Дополняет C4 Container Diagram физическим уровнем.

```mermaid
flowchart TB
    subgraph Internet
        TG[Telegram Bot API + Stars]
        USER[Пользователи]
        ADMIN[Администраторы]
    end

    subgraph Edge["Edge (CDN + WAF)"]
        CDN[Cloudflare CDN]
    end

    subgraph K8S["Kubernetes Cluster"]
        subgraph Ingress["Ingress (nginx-ingress)"]
            ING[TLS termination, routing]
        end

        subgraph App["Application namespace"]
            API1[backend-api pod #1]
            API2[backend-api pod #2]
            BOT[bot-webhook pod]
            BW[broadcast-worker deployment]
            VW[video-polling-worker deployment]
            CRON[worker CronJobs]
            MINI[mini-app static pod]
            CRM[admin-crm pod]
        end

        subgraph Data["Data namespace"]
            PG[(PostgreSQL Primary)]
            PG_R[(PostgreSQL Replica)]
            REDIS[(Redis Master)]
            REDIS_R[(Redis Replica)]
        end

        subgraph Obs["Observability namespace"]
            PROM[Prometheus]
            GRAF[Grafana]
            SENTRY[Sentry self-hosted / SaaS]
        end
    end

    USER -->|HTTPS| CDN
    ADMIN -->|HTTPS| CDN
    TG -->|Webhook| CDN

    CDN --> ING
    ING -->|/api/v1| API1
    ING -->|/api/v1| API2
    ING -->|/bot/webhook| BOT
    ING -->|/| MINI
    ING -->|/admin| CRM

    API1 --> PG
    API2 --> PG
    BOT --> PG
    BW --> PG
    VW --> PG
    CRON --> PG

    API1 --> REDIS
    API2 --> REDIS
    BOT --> REDIS
    BW --> REDIS
    VW --> REDIS

    PG -. async replication .-> PG_R
    REDIS -. replication .-> REDIS_R

    API1 -.metrics.-> PROM
    BW -.logs/status.-> PROM
    PROM --> GRAF
    API1 -.errors.-> SENTRY
```

## Окружения

| Среда | Назначение | Ресурсы | Replicas API |
|-------|-----------|---------|--------------|
| `dev`     | Локально через docker-compose | 1× БД, 1× Redis | 1 |
| `staging` | E2E тесты, демонстрации        | Managed Postgres small, Redis small | 1 |
| `prod`    | Боевой                          | Managed Postgres HA, Redis HA | 2+ HPA |

## Blue/Green и миграции

Изменения схемы БД проходят строго через Alembic, без downtime — см. [ADR-005](../adr/0005-database-migrations.md).

## Секреты

- `bot_token`, `admin_jwt_secret`, `db_password`, `redis_password` — k8s `Secret` (sealed-secrets).
- В deve и staging — `.env` через docker-compose.

## Бэкапы

- PostgreSQL: ежедневный логический + WAL archive (PITR 7 дней).
- Redis: не критичен (кэш + rate-limit state), но snapshot раз в час.

## Масштабирование

- `backend-api`: HPA по CPU + кастомной метрике `requests_per_second`.
- `broadcast-worker` и `video-polling-worker`: отдельные one-replica
  Deployments; ежедневные jobs масштабируются расписанием CronJob.
- PostgreSQL: вертикально + read-replica для аналитики CRM.
